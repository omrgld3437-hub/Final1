"""Boot ID: sunucu her açılışta yeni ID. İstemci eşleşmezse oturum iptal (tüm hesaplardan çıkış)."""

import uuid

BOOT_ID: str = ""


def set_boot_id() -> str:
    global BOOT_ID
    BOOT_ID = str(uuid.uuid4())
    return BOOT_ID


def get_boot_id() -> str:
    return BOOT_ID or ""
