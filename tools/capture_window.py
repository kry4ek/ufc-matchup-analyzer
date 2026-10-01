"""Capture only our own Tk window, for release-documentation screenshots."""
import ctypes
from ctypes import wintypes
from pathlib import Path
import struct
import zlib

def capture(window,path):
    window.update()
    user=ctypes.WinDLL('user32',use_last_error=True);gdi=ctypes.WinDLL('gdi32',use_last_error=True)
    user.GetParent.argtypes=[wintypes.HWND];user.GetParent.restype=wintypes.HWND
    user.GetWindowDC.argtypes=[wintypes.HWND];user.GetWindowDC.restype=wintypes.HDC
    user.ReleaseDC.argtypes=[wintypes.HWND,wintypes.HDC]
    user.GetWindowRect.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.RECT)]
    user.PrintWindow.argtypes=[wintypes.HWND,wintypes.HDC,wintypes.UINT]
    gdi.CreateCompatibleDC.argtypes=[wintypes.HDC];gdi.CreateCompatibleDC.restype=wintypes.HDC
    gdi.CreateCompatibleBitmap.argtypes=[wintypes.HDC,ctypes.c_int,ctypes.c_int];gdi.CreateCompatibleBitmap.restype=wintypes.HBITMAP
    gdi.SelectObject.argtypes=[wintypes.HDC,wintypes.HANDLE];gdi.SelectObject.restype=wintypes.HANDLE
    gdi.GetDIBits.argtypes=[wintypes.HDC,wintypes.HBITMAP,wintypes.UINT,wintypes.UINT,ctypes.c_void_p,ctypes.c_void_p,wintypes.UINT]
    gdi.DeleteObject.argtypes=[wintypes.HANDLE];gdi.DeleteDC.argtypes=[wintypes.HDC]
    handle=user.GetParent(window.winfo_id());rect=wintypes.RECT();user.GetWindowRect(handle,ctypes.byref(rect))
    width=rect.right-rect.left;height=rect.bottom-rect.top
    source=user.GetWindowDC(handle);target=gdi.CreateCompatibleDC(source);bitmap=gdi.CreateCompatibleBitmap(source,width,height);old=gdi.SelectObject(target,bitmap)
    class Header(ctypes.Structure):
        _fields_=[('size',wintypes.DWORD),('width',ctypes.c_long),('height',ctypes.c_long),('planes',wintypes.WORD),('bits',wintypes.WORD),('compression',wintypes.DWORD),('image_size',wintypes.DWORD),('xppm',ctypes.c_long),('yppm',ctypes.c_long),('used',wintypes.DWORD),('important',wintypes.DWORD)]
    try:
        if not user.PrintWindow(handle,target,2):raise RuntimeError('Could not capture the app window')
        gdi.SelectObject(target,old)
        header=Header(40,width,-height,1,32,0,0,0,0,0,0);buffer=ctypes.create_string_buffer(width*height*4)
        if not gdi.GetDIBits(target,bitmap,0,height,buffer,ctypes.byref(header),0):raise RuntimeError('Could not read the app screenshot')
        pixels=buffer.raw;rows=[]
        for y in range(height):
            row=pixels[y*width*4:(y+1)*width*4];rgb=bytearray(width*3)
            rgb[0::3]=row[2::4];rgb[1::3]=row[1::4];rgb[2::3]=row[0::4];rows.append(b'\0'+rgb)
        def chunk(kind,value):return struct.pack('!I',len(value))+kind+value+struct.pack('!I',zlib.crc32(kind+value)&0xffffffff)
        png=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('!2I5B',width,height,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(b''.join(rows)))+chunk(b'IEND',b'')
        path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(png)
    finally:
        gdi.DeleteObject(bitmap);gdi.DeleteDC(target);user.ReleaseDC(handle,source)
