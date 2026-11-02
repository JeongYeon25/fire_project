"""사진 업로드: 검사(이미지만, 5MB 이하)와 긴 변 1600px 축소."""

import io
import uuid
from datetime import timedelta

from django import forms
from django.core.files.base import ContentFile
from django.utils import timezone
from PIL import Image, ImageOps, UnidentifiedImageError

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_SIDE = 1600
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP", "GIF"}
DATETIME_INPUT = "%Y-%m-%dT%H:%M"


def resize_image(uploaded):
    """업로드 파일을 열어 회전을 바로잡고 긴 변을 1600px 이하로 줄인다. (ContentFile, 확장자)."""
    uploaded.seek(0)
    try:
        with Image.open(uploaded) as img:
            fmt = img.format
            if fmt not in ALLOWED_FORMATS:
                raise forms.ValidationError("JPG, PNG, WebP, GIF 사진만 올릴 수 있어요.")
            img.seek(0)  # 움직이는 GIF는 첫 장면만
            img = ImageOps.exif_transpose(img)
            img.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
            has_alpha = img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)
            buf = io.BytesIO()
            if has_alpha:
                img.convert("RGBA").save(buf, "PNG", optimize=True)
                ext = "png"
            else:
                img.convert("RGB").save(buf, "JPEG", quality=85, optimize=True)
                ext = "jpg"
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError):
        raise forms.ValidationError("사진 파일을 열 수 없어요. 다른 사진으로 다시 올려 주세요.")
    return ContentFile(buf.getvalue()), ext


class PhotoUploadForm(forms.Form):
    plant = forms.ModelChoiceField(queryset=None, label="화분", empty_label=None)
    image = forms.ImageField(label="사진 파일", error_messages={"required": "사진 파일을 골라 주세요."})
    taken_at = forms.DateTimeField(label="촬영 시각", input_formats=[DATETIME_INPUT])

    def __init__(self, *args, owner=None, **kwargs):
        from .models import Plant

        super().__init__(*args, **kwargs)
        self.fields["plant"].queryset = Plant.objects.filter(owner=owner)
        self.fields["plant"].label_from_instance = lambda p: p.title
        self.fields["image"].error_messages["invalid_image"] = "이미지 파일만 올릴 수 있어요."

    def clean_image(self):
        image = self.cleaned_data["image"]
        if image.size > MAX_UPLOAD_BYTES:
            raise forms.ValidationError("사진은 5MB 이하만 올릴 수 있어요.")
        self.processed, self.ext = resize_image(image)
        return image

    def clean_taken_at(self):
        taken_at = self.cleaned_data["taken_at"]
        if taken_at > timezone.now() + timedelta(minutes=5):
            raise forms.ValidationError("촬영 시각이 지금보다 뒤일 수는 없어요.")
        return taken_at

    def save(self):
        from .models import PlantPhoto

        photo = PlantPhoto(plant=self.cleaned_data["plant"], taken_at=self.cleaned_data["taken_at"])
        photo.image.save(f"{uuid.uuid4().hex}.{self.ext}", self.processed, save=False)
        photo.save()
        return photo


def now_input_value():
    return timezone.localtime().strftime(DATETIME_INPUT)
