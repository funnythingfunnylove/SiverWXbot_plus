"""Test-only import stubs. They do not simulate or validate WeChat automation."""
import sys
import types


def install():
    wx = types.ModuleType("wxautox4")
    def unavailable(*args, **kwargs):
        raise RuntimeError("Real WeChat is unavailable in this test harness")
    wx.WeChat = unavailable
    wx.WxParam = type("WxParam", (), {})
    sys.modules["wxautox4"] = wx
    sys.modules["wxautox4.msgs"] = types.ModuleType("wxautox4.msgs")
    sys.modules["wxautox4.utils"] = types.ModuleType("wxautox4.utils")
    useful = types.ModuleType("wxautox4.utils.useful")
    useful.check_license = lambda: False
    sys.modules["wxautox4.utils.useful"] = useful
    com = types.ModuleType("pythoncom")
    com.CoInitialize = com.CoUninitialize = unavailable
    sys.modules["pythoncom"] = com
