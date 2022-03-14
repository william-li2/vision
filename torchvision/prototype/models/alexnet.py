from functools import partial
from typing import Any, Optional

from torchvision.prototype.transforms import ImageClassificationEval
from torchvision.transforms.functional import InterpolationMode

from ...models.alexnet import AlexNet
from ._api import WeightsEnum, Weights
from ._meta import _IMAGENET_CATEGORIES
from ._utils import handle_legacy_interface, _ovewrite_named_param


__all__ = ["AlexNet", "AlexNet_Weights", "alexnet"]


class AlexNet_Weights(WeightsEnum):
    IMAGENET1K_V1 = Weights(
        url="https://download.pytorch.org/models/alexnet-owt-7be5be79.pth",
        transforms=partial(ImageClassificationEval, crop_size=224),
        meta={
            "task": "image_classification",
            "architecture": "AlexNet",
            "publication_year": 2012,
            "num_params": 61100840,
            "size": (224, 224),
            "min_size": (63, 63),
            "categories": _IMAGENET_CATEGORIES,
            "interpolation": InterpolationMode.BILINEAR,
            "recipe": "https://github.com/pytorch/vision/tree/main/references/classification#alexnet-and-vgg",
            "acc@1": 56.522,
            "acc@5": 79.066,
        },
    )
    DEFAULT = IMAGENET1K_V1


@handle_legacy_interface(weights=("pretrained", AlexNet_Weights.IMAGENET1K_V1))
def alexnet(*, weights: Optional[AlexNet_Weights] = None, progress: bool = True, **kwargs: Any) -> AlexNet:
    weights = AlexNet_Weights.verify(weights)

    if weights is not None:
        _ovewrite_named_param(kwargs, "num_classes", len(weights.meta["categories"]))

    model = AlexNet(**kwargs)

    if weights is not None:
        model.load_state_dict(weights.get_state_dict(progress=progress))

    return model
