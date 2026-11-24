"""CAPTCHA text and image. Pure Pillow, no storage."""
import io
import random
import secrets

from PIL import Image, ImageDraw, ImageFilter, ImageFont

# Latin letters and digits (the assignment) without look-alikes: 0/O/o, 1/l/I, 5/S/s, 2/Z/z, 8/B, u/v
ALPHABET = 'abcdefghjkmnpqrtwxyACDEFGHJKLMNPQRTWXY34679'


class CaptchaGenerator:
    def __init__(self, length: int = 5, width: int = 180, height: int = 60, font_size: int = 36):
        self.length = length
        self.width = width
        self.height = height
        self.font = ImageFont.load_default(size=font_size)
        self._random = random.SystemRandom()

    def text(self) -> str:
        return ''.join(secrets.choice(ALPHABET) for _ in range(self.length))

    def image(self, text: str) -> bytes:
        """PNG with rotated, shifted characters, noise lines and dots, slightly blurred."""
        rnd = self._random
        image = Image.new('RGB', (self.width, self.height), (245, 246, 250))
        draw = ImageDraw.Draw(image)

        for _ in range(250):
            draw.point((rnd.randrange(self.width), rnd.randrange(self.height)), fill=self._color(150, 220))

        step = (self.width - 20) / len(text)
        for index, char in enumerate(text):
            glyph = Image.new('RGBA', (self.height, self.height), (0, 0, 0, 0))
            ImageDraw.Draw(glyph).text((self.height / 2, self.height / 2), char, font=self.font,
                                       fill=self._color(20, 110), anchor='mm')
            glyph = glyph.rotate(rnd.uniform(-30, 30), resample=Image.Resampling.BICUBIC)
            x = int(10 + index * step + rnd.uniform(-3, 3) - (self.height - step) / 2)
            y = int(rnd.uniform(-6, 6))
            image.paste(glyph, (x, y), glyph)

        for _ in range(4):
            points = [(rnd.randrange(self.width), rnd.randrange(self.height)) for _ in range(3)]
            draw.line(points, fill=self._color(60, 160), width=2)

        image = image.filter(ImageFilter.GaussianBlur(0.6))
        buffer = io.BytesIO()
        image.save(buffer, format='PNG', optimize=True)
        return buffer.getvalue()

    def _color(self, low: int, high: int) -> tuple[int, int, int]:
        return tuple(self._random.randint(low, high) for _ in range(3))
