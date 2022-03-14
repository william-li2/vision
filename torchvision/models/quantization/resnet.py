from functools import partial
from typing import Any, Type, Union, List, Optional

import torch
import torch.nn as nn
from torch import Tensor
from torchvision.models.resnet import (
    Bottleneck,
    BasicBlock,
    ResNet,
    ResNet18_Weights,
    ResNet50_Weights,
    ResNeXt101_32X8D_Weights,
)

from ...transforms import ImageClassificationEval, InterpolationMode
from .._api import WeightsEnum, Weights
from .._meta import _IMAGENET_CATEGORIES
from .._utils import handle_legacy_interface, _ovewrite_named_param
from .utils import _fuse_modules, _replace_relu, quantize_model


__all__ = [
    "QuantizableResNet",
    "ResNet18_QuantizedWeights",
    "ResNet50_QuantizedWeights",
    "ResNeXt101_32X8D_QuantizedWeights",
    "resnet18",
    "resnet50",
    "resnext101_32x8d",
]


class QuantizableBasicBlock(BasicBlock):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.add_relu = torch.nn.quantized.FloatFunctional()

    def forward(self, x: Tensor) -> Tensor:
        identity = x

        out = self.conv1(x)
        out = self.bn1(out)
        out = self.relu(out)

        out = self.conv2(out)
        out = self.bn2(out)

        if self.downsample is not None:
            identity = self.downsample(x)

        out = self.add_relu.add_relu(out, identity)

        return out

    def fuse_model(self, is_qat: Optional[bool] = None) -> None:
        _fuse_modules(self, [["conv1", "bn1", "relu"], ["conv2", "bn2"]], is_qat, inplace=True)
        if self.downsample:
            _fuse_modules(self.downsample, ["0", "1"], is_qat, inplace=True)


class QuantizableBottleneck(Bottleneck):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.skip_add_relu = nn.quantized.FloatFunctional()
        self.relu1 = nn.ReLU(inplace=False)
        self.relu2 = nn.ReLU(inplace=False)

    def forward(self, x: Tensor) -> Tensor:
        identity = x
        out = self.conv1(x)
        out = self.bn1(out)
        out = self.relu1(out)
        out = self.conv2(out)
        out = self.bn2(out)
        out = self.relu2(out)

        out = self.conv3(out)
        out = self.bn3(out)

        if self.downsample is not None:
            identity = self.downsample(x)
        out = self.skip_add_relu.add_relu(out, identity)

        return out

    def fuse_model(self, is_qat: Optional[bool] = None) -> None:
        _fuse_modules(
            self, [["conv1", "bn1", "relu1"], ["conv2", "bn2", "relu2"], ["conv3", "bn3"]], is_qat, inplace=True
        )
        if self.downsample:
            _fuse_modules(self.downsample, ["0", "1"], is_qat, inplace=True)


class QuantizableResNet(ResNet):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)

        self.quant = torch.ao.quantization.QuantStub()
        self.dequant = torch.ao.quantization.DeQuantStub()

    def forward(self, x: Tensor) -> Tensor:
        x = self.quant(x)
        # Ensure scriptability
        # super(QuantizableResNet,self).forward(x)
        # is not scriptable
        x = self._forward_impl(x)
        x = self.dequant(x)
        return x

    def fuse_model(self, is_qat: Optional[bool] = None) -> None:
        r"""Fuse conv/bn/relu modules in resnet models

        Fuse conv+bn+relu/ Conv+relu/conv+Bn modules to prepare for quantization.
        Model is modified in place.  Note that this operation does not change numerics
        and the model after modification is in floating point
        """
        _fuse_modules(self, ["conv1", "bn1", "relu"], is_qat, inplace=True)
        for m in self.modules():
            if type(m) is QuantizableBottleneck or type(m) is QuantizableBasicBlock:
                m.fuse_model(is_qat)


def _resnet(
    block: Type[Union[QuantizableBasicBlock, QuantizableBottleneck]],
    layers: List[int],
    weights: Optional[WeightsEnum],
    progress: bool,
    quantize: bool,
    **kwargs: Any,
) -> QuantizableResNet:
    if weights is not None:
        _ovewrite_named_param(kwargs, "num_classes", len(weights.meta["categories"]))
        if "backend" in weights.meta:
            _ovewrite_named_param(kwargs, "backend", weights.meta["backend"])
    backend = kwargs.pop("backend", "fbgemm")

    model = QuantizableResNet(block, layers, **kwargs)
    _replace_relu(model)
    if quantize:
        quantize_model(model, backend)

    if weights is not None:
        model.load_state_dict(weights.get_state_dict(progress=progress))

    return model


_COMMON_META = {
    "task": "image_classification",
    "size": (224, 224),
    "min_size": (1, 1),
    "categories": _IMAGENET_CATEGORIES,
    "interpolation": InterpolationMode.BILINEAR,
    "backend": "fbgemm",
    "quantization": "ptq",
    "recipe": "https://github.com/pytorch/vision/tree/main/references/classification#post-training-quantized-models",
}


class ResNet18_QuantizedWeights(WeightsEnum):
    IMAGENET1K_FBGEMM_V1 = Weights(
        url="https://download.pytorch.org/models/quantized/resnet18_fbgemm_16fa66dd.pth",
        transforms=partial(ImageClassificationEval, crop_size=224),
        meta={
            **_COMMON_META,
            "architecture": "ResNet",
            "publication_year": 2015,
            "num_params": 11689512,
            "unquantized": ResNet18_Weights.IMAGENET1K_V1,
            "acc@1": 69.494,
            "acc@5": 88.882,
        },
    )
    DEFAULT = IMAGENET1K_FBGEMM_V1


class ResNet50_QuantizedWeights(WeightsEnum):
    IMAGENET1K_FBGEMM_V1 = Weights(
        url="https://download.pytorch.org/models/quantized/resnet50_fbgemm_bf931d71.pth",
        transforms=partial(ImageClassificationEval, crop_size=224),
        meta={
            **_COMMON_META,
            "architecture": "ResNet",
            "publication_year": 2015,
            "num_params": 25557032,
            "unquantized": ResNet50_Weights.IMAGENET1K_V1,
            "acc@1": 75.920,
            "acc@5": 92.814,
        },
    )
    IMAGENET1K_FBGEMM_V2 = Weights(
        url="https://download.pytorch.org/models/quantized/resnet50_fbgemm-23753f79.pth",
        transforms=partial(ImageClassificationEval, crop_size=224, resize_size=232),
        meta={
            **_COMMON_META,
            "architecture": "ResNet",
            "publication_year": 2015,
            "num_params": 25557032,
            "unquantized": ResNet50_Weights.IMAGENET1K_V2,
            "acc@1": 80.282,
            "acc@5": 94.976,
        },
    )
    DEFAULT = IMAGENET1K_FBGEMM_V2


class ResNeXt101_32X8D_QuantizedWeights(WeightsEnum):
    IMAGENET1K_FBGEMM_V1 = Weights(
        url="https://download.pytorch.org/models/quantized/resnext101_32x8_fbgemm_09835ccf.pth",
        transforms=partial(ImageClassificationEval, crop_size=224),
        meta={
            **_COMMON_META,
            "architecture": "ResNeXt",
            "publication_year": 2016,
            "num_params": 88791336,
            "unquantized": ResNeXt101_32X8D_Weights.IMAGENET1K_V1,
            "acc@1": 78.986,
            "acc@5": 94.480,
        },
    )
    IMAGENET1K_FBGEMM_V2 = Weights(
        url="https://download.pytorch.org/models/quantized/resnext101_32x8_fbgemm-ee16d00c.pth",
        transforms=partial(ImageClassificationEval, crop_size=224, resize_size=232),
        meta={
            **_COMMON_META,
            "architecture": "ResNeXt",
            "publication_year": 2016,
            "num_params": 88791336,
            "unquantized": ResNeXt101_32X8D_Weights.IMAGENET1K_V2,
            "acc@1": 82.574,
            "acc@5": 96.132,
        },
    )
    DEFAULT = IMAGENET1K_FBGEMM_V2


@handle_legacy_interface(
    weights=(
        "pretrained",
        lambda kwargs: ResNet18_QuantizedWeights.IMAGENET1K_FBGEMM_V1
        if kwargs.get("quantize", False)
        else ResNet18_Weights.IMAGENET1K_V1,
    )
)
def resnet18(
    *,
    weights: Optional[Union[ResNet18_QuantizedWeights, ResNet18_Weights]] = None,
    progress: bool = True,
    quantize: bool = False,
    **kwargs: Any,
) -> QuantizableResNet:
    r"""ResNet-18 model from
    `"Deep Residual Learning for Image Recognition" <https://arxiv.org/pdf/1512.03385.pdf>`_

    Args:
        weights (ResNet18_QuantizedWeights or ResNet18_Weights, optional): The pretrained
            weights for the model
        progress (bool): If True, displays a progress bar of the download to stderr
        quantize (bool): If True, return a quantized version of the model
    """
    weights = (ResNet18_QuantizedWeights if quantize else ResNet18_Weights).verify(weights)

    return _resnet(QuantizableBasicBlock, [2, 2, 2, 2], weights, progress, quantize, **kwargs)


@handle_legacy_interface(
    weights=(
        "pretrained",
        lambda kwargs: ResNet50_QuantizedWeights.IMAGENET1K_FBGEMM_V1
        if kwargs.get("quantize", False)
        else ResNet50_Weights.IMAGENET1K_V1,
    )
)
def resnet50(
    *,
    weights: Optional[Union[ResNet50_QuantizedWeights, ResNet50_Weights]] = None,
    progress: bool = True,
    quantize: bool = False,
    **kwargs: Any,
) -> QuantizableResNet:
    r"""ResNet-50 model from
    `"Deep Residual Learning for Image Recognition" <https://arxiv.org/pdf/1512.03385.pdf>`_

    Args:
        weights (ResNet50_QuantizedWeights or ResNet50_Weights, optional): The pretrained
            weights for the model
        progress (bool): If True, displays a progress bar of the download to stderr
        quantize (bool): If True, return a quantized version of the model
    """
    weights = (ResNet50_QuantizedWeights if quantize else ResNet50_Weights).verify(weights)

    return _resnet(QuantizableBottleneck, [3, 4, 6, 3], weights, progress, quantize, **kwargs)


@handle_legacy_interface(
    weights=(
        "pretrained",
        lambda kwargs: ResNeXt101_32X8D_QuantizedWeights.IMAGENET1K_FBGEMM_V1
        if kwargs.get("quantize", False)
        else ResNeXt101_32X8D_Weights.IMAGENET1K_V1,
    )
)
def resnext101_32x8d(
    *,
    weights: Optional[Union[ResNeXt101_32X8D_QuantizedWeights, ResNeXt101_32X8D_Weights]] = None,
    progress: bool = True,
    quantize: bool = False,
    **kwargs: Any,
) -> QuantizableResNet:
    r"""ResNeXt-101 32x8d model from
    `"Aggregated Residual Transformation for Deep Neural Networks" <https://arxiv.org/pdf/1611.05431.pdf>`_

    Args:
        weights (ResNeXt101_32X8D_QuantizedWeights or ResNeXt101_32X8D_Weights, optional): The pretrained
            weights for the model
        progress (bool): If True, displays a progress bar of the download to stderr
        quantize (bool): If True, return a quantized version of the model
    """
    weights = (ResNeXt101_32X8D_QuantizedWeights if quantize else ResNeXt101_32X8D_Weights).verify(weights)

    _ovewrite_named_param(kwargs, "groups", 32)
    _ovewrite_named_param(kwargs, "width_per_group", 8)
    return _resnet(QuantizableBottleneck, [3, 4, 23, 3], weights, progress, quantize, **kwargs)
