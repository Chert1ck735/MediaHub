"""Сервис для хеширования и проверки паролей."""

import bcrypt


class PasswordService:
    """Отвечает только за работу с паролями."""

    @staticmethod
    def _prepare_password_bytes(password: str) -> bytes:
        """Преобразует пароль в bytes и ограничивает длину для bcrypt."""

        return password.encode("utf-8")[:72]

    def hash_password(self, password: str) -> str:
        """Возвращает bcrypt-хеш пароля."""

        hashed = bcrypt.hashpw(
            self._prepare_password_bytes(password),
            bcrypt.gensalt(),
        )
        return hashed.decode("utf-8")

    def verify_password(self, plain: str, hashed: str) -> bool:
        """Проверяет обычный пароль с bcrypt-хешем."""

        try:
            return bcrypt.checkpw(
                self._prepare_password_bytes(plain),
                hashed.encode("utf-8"),
            )
        except ValueError:
            return False
