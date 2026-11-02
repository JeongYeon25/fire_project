from django import forms
from django.contrib.auth import get_user_model, password_validation

from plants.models import Crop

User = get_user_model()


class SignupForm(forms.Form):
    nickname = forms.CharField(label="닉네임", max_length=20, widget=forms.TextInput(attrs={"autocomplete": "nickname"}))
    password = forms.CharField(
        label="비밀번호", widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        help_text="8자 이상, 숫자만으로는 만들 수 없어요.",
    )
    def clean_nickname(self):
        nickname = self.cleaned_data["nickname"].strip()
        if not nickname:
            raise forms.ValidationError("닉네임을 입력해 주세요.")
        if User.objects.filter(username__iexact=nickname).exists():
            raise forms.ValidationError("이미 쓰고 있는 닉네임이에요.")
        return nickname

    def clean(self):
        data = super().clean()
        password = data.get("password")
        if password and data.get("nickname"):
            try:
                password_validation.validate_password(password, User(username=data["nickname"]))
            except forms.ValidationError as e:
                self.add_error("password", e)
        return data


class LoginForm(forms.Form):
    nickname = forms.CharField(label="닉네임", max_length=150, widget=forms.TextInput(attrs={"autocomplete": "username"}))
    password = forms.CharField(label="비밀번호", widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}))


class CropChoiceForm(forms.Form):
    crop = forms.ModelChoiceField(
        queryset=Crop.objects.filter(is_active=True), empty_label=None, error_messages={"required": "작물을 골라 주세요."}
    )


