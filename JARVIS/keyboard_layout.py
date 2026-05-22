import platform


def switch_to_english_layout() -> bool:
    if platform.system().lower() != "windows":
        return False

    try:
        import ctypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        english_hkl = user32.LoadKeyboardLayoutW("00000409", 1)
        if not english_hkl:
            return False

        user32.ActivateKeyboardLayout(english_hkl, 0)
        hwnd_broadcast = 0xFFFF
        wm_inputlangchangerequest = 0x0050
        user32.PostMessageW(hwnd_broadcast, wm_inputlangchangerequest, 0, english_hkl)
        return True
    except Exception:
        return False
