from django.core.validators import MaxLengthValidator, MinLengthValidator
from rest_framework import serializers

from accounts.models import username_validator

from .models import Attachment, Comment
from .services import NewComment

TEXT_MAX_LENGTH = 5000


def text_field() -> serializers.CharField:
    """The comment text: the same rules for posting and preview."""
    return serializers.CharField(
        trim_whitespace=True, validators=[MaxLengthValidator(TEXT_MAX_LENGTH)],
        help_text='Allowed tags: <a href="" title="">, <code>, <i>, <strong>; every tag closed (XHTML)',
    )


class CommentPreviewSerializer(serializers.Serializer):
    text = text_field()


class CommentPreviewResultSerializer(serializers.Serializer):
    text = serializers.CharField(help_text='Sanitized HTML exactly as it will be stored and shown')


class CommentCreateSerializer(serializers.Serializer):
    """Field formats (the same rules as the frontend form). Markup, parent and CAPTCHA are checked by the service."""

    user_name = serializers.CharField(
        max_length=50, validators=[MinLengthValidator(2), username_validator],
        help_text='Latin letters and digits, 2-50 characters',
    )
    email = serializers.EmailField(max_length=254)
    home_page = serializers.URLField(
        max_length=200, required=False, allow_blank=True, default='',
        help_text='http(s) URL, optional',
    )
    text = text_field()
    parent = serializers.IntegerField(required=False, allow_null=True, default=None, min_value=1,
                                      help_text='Id of the comment this one replies to')
    captcha_key = serializers.CharField(max_length=64)
    captcha_answer = serializers.CharField(max_length=10)
    attachment = serializers.FileField(
        required=False, allow_null=True, default=None, max_length=255,
        help_text='Optional: a JPG / GIF / PNG image (fitted into 320x240) or a TXT file up to 100 KB. '
                  'Send the form as multipart/form-data.',
    )

    def validate_home_page(self, value: str) -> str:
        if value and not value.lower().startswith(('http://', 'https://')):
            raise serializers.ValidationError('Only http:// and https:// addresses.')
        return value

    def to_new_comment(self) -> NewComment:
        data = self.validated_data
        return NewComment(
            user_name=data['user_name'],
            email=data['email'],
            home_page=data['home_page'],
            text=data['text'],
            parent_id=data['parent'],
            captcha_key=data['captcha_key'],
            captcha_answer=data['captcha_answer'],
            attachment=data['attachment'],
        )


class AttachmentSerializer(serializers.ModelSerializer):
    url = serializers.FileField(source='file', read_only=True, use_url=True)

    class Meta:
        model = Attachment
        fields = ('id', 'kind', 'url', 'original_name', 'size', 'width', 'height', 'status')
        read_only_fields = fields


class CommentSerializer(serializers.ModelSerializer):
    """Public view of a comment: never exposes ip, user agent, guest key or the shadow flag."""

    attachments = AttachmentSerializer(many=True, read_only=True)

    class Meta:
        model = Comment
        fields = (
            'id', 'parent', 'root', 'depth', 'user_name', 'email', 'home_page', 'text',
            'is_ufo', 'replies_count', 'score', 'created_at', 'attachments',
        )
        read_only_fields = fields
