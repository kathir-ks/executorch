# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

import unittest
from contextlib import contextmanager

import torch
from executorch.exir import EdgeCompileConfig, to_edge

from executorch.exir.dialects._ops import ops
from torch._export.verifier import SpecViolationError
from torch.ao.quantization.fx._decomposed import quantized_decomposed_lib  # noqa: F401
from torch.export import export

from ..verifier import EXIREdgeDialectVerifier


class TestEdgeDialectVerifier(unittest.TestCase):
    @contextmanager
    def assertNotRaises(self, exc_type):
        try:
            yield None
        except exc_type:
            raise self.failureException("{} raised".format(exc_type.__name__))

    def test_edge_verifier_check_valid_op_succeed_given_custom_op(self) -> None:
        edge_op = ops.edge.quantized_decomposed.quantize_per_tensor.default
        verifier = EXIREdgeDialectVerifier()
        with self.assertNotRaises(SpecViolationError):
            verifier.check_valid_edge_op(edge_op)
            verifier.check_valid_op(edge_op)

    def test_edge_verifier_enablement(self) -> None:
        class M(torch.nn.Module):
            def forward(self, x, y):
                z = y.item()
                torch._constrain_as_value(z, 0, 4)
                return x[z : z + y.shape[0]]

        ep = torch.export.export(M(), (torch.randn(10), torch.tensor([3])))

        compile_config_with_disable_ir_validity = EdgeCompileConfig(
            _check_ir_validity=False
        )
        edge_manager = to_edge(
            ep, compile_config=compile_config_with_disable_ir_validity
        )

        normal_verifier = EXIREdgeDialectVerifier()
        disable_ir_validity_verifier = EXIREdgeDialectVerifier(
            compile_config_with_disable_ir_validity
        )

        # exported model can not pass normal verifier due to
        # aten.sym_constrain_range.default is illegal to be edge op
        with self.assertRaises(SpecViolationError):
            normal_verifier(edge_manager.exported_program())

        # exported model can pass disable_ir_validity_verifier due to verifier
        # is disabled by compile_config_with_disable_ir_validity
        # (_check_ir_validity=False). Noted that this verifation has been done
        # when calling `to_edge`. Explicitly calling verifier here just for better
        # demonstration and is unnecessary in real world for ir verification.
        disable_ir_validity_verifier(edge_manager.exported_program())

    def test_edge_verifier_check_edge_op(self) -> None:
        class Model(torch.nn.Module):
            def __init__(self):
                super().__init__()

            def forward(self, x: torch.Tensor) -> torch.Tensor:
                return x.transpose(0, 1)

        m = Model().eval()

        example_input = (torch.zeros([2, 2]),)

        export_model = export(m, example_input)

        # In default we use dim order.
        compile_config_without_edge_op = EdgeCompileConfig(_use_edge_ops=False)

        edge_manager = to_edge(
            export_model, compile_config=compile_config_without_edge_op
        )

        normal_verifier = EXIREdgeDialectVerifier()
        disable_edge_op_check_verifier = EXIREdgeDialectVerifier(
            compile_config_without_edge_op
        )

        # exported model can not pass normal verifier due to
        # incontiguous memory layout tensor is not supported in ET
        with self.assertRaises(SpecViolationError):
            normal_verifier(edge_manager.exported_program())

        # exported model can pass disable_edge_op_check_verifier due to the
        # incontiguous memory layout tensor verification is disabled by
        # compile_config_without_edge_op (_use_edge_ops=False). Noted that this
        # verifation has been done when calling `to_edge`. Explicitly calling
        # verifier here just for better demonstration and is unnecessary
        # in real world for ir verification.
        disable_edge_op_check_verifier(edge_manager.exported_program())
