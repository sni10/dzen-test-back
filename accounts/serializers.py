from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import MinLengthValidator
from rest_framework import serializers

from .models import User, username_validator


class RegisterSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=50, validators=[MinLengthValidator(2), username_validator],
                                     help_text='Latin letters and digits, 2-50 characters (as in the comment form)')
    email = serializers.EmailField(max_length=254)
    password = serializers.CharField(write_only=True, max_length=128, trim_whitespace=False)
    captcha_key = serializers.CharField(max_length=64)
    captcha_answer = serializers.CharField(max_length=10)

    def validate(self, data):
        candidate = User(username=data['username'], email=data['email'])
        try:
            validate_password(data['password'], user=candidate)
        except DjangoValidationError as error:
            raise serializers.ValidationError({'password': list(error.messages)}) from None
        return data


class LoginSerializer(serializers.Serializer):
    login = serializers.CharField(max_length=254, help_text='User name or e-mail')
    password = serializers.CharField(write_only=True, max_length=128, trim_whitespace=False)


class MeSerializer(serializers.ModelSerializer):
    home_page = serializers.URLField(read_only=True)
    is_moderator = serializers.BooleanField(read_only=True)

    class Meta:
        model = User
        fields = ('id', 'username', 'email', 'home_page', 'is_moderator')
        read_only_fields = fields


class SessionSerializer(serializers.Serializer):
    access = serializers.CharField(help_text='Send as "Authorization: Bearer <access>"; lives 15 minutes')
    user = MeSerializer()
