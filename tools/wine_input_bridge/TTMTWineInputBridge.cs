using System;
using System.Collections.Generic;
using System.Net;
using System.Net.Sockets;
using System.Runtime.InteropServices;
using System.Text;

public static class TTMTWineInputBridge
{
    private const int WM_KEYDOWN = 0x0100;
    private const int WM_KEYUP = 0x0101;
    private const int WM_SYSKEYDOWN = 0x0104;
    private const int WM_SYSKEYUP = 0x0105;
    private const uint MAPVK_VK_TO_VSC = 0;

    private delegate bool EnumWindowsProc(IntPtr hwnd, IntPtr lParam);

    [StructLayout(LayoutKind.Sequential)]
    private struct RECT
    {
        public int Left;
        public int Top;
        public int Right;
        public int Bottom;
    }

    private sealed class GameWindow
    {
        public IntPtr Hwnd;
        public string Title = "";
        public RECT Rect;
    }

    [DllImport("user32.dll")]
    private static extern bool EnumWindows(EnumWindowsProc callback, IntPtr lParam);

    [DllImport("user32.dll")]
    private static extern bool IsWindowVisible(IntPtr hwnd);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern int GetWindowTextW(IntPtr hwnd, StringBuilder text, int count);

    [DllImport("user32.dll")]
    private static extern bool GetWindowRect(IntPtr hwnd, out RECT rect);

    [DllImport("user32.dll")]
    private static extern IntPtr GetForegroundWindow();

    [DllImport("user32.dll")]
    private static extern bool PostMessageW(IntPtr hwnd, int msg, IntPtr wParam, IntPtr lParam);

    [DllImport("user32.dll")]
    private static extern uint MapVirtualKeyW(uint code, uint mapType);

    public static int Main(string[] args)
    {
        int port = 37377;
        if (args.Length >= 2 && args[0] == "--port")
            int.TryParse(args[1], out port);

        var listener = new TcpListener(IPAddress.Loopback, port);
        listener.Start();
        Console.WriteLine("TTMTWineInputBridge listening on 127.0.0.1:" + port);
        Console.Out.Flush();

        while (true)
        {
            using (var client = listener.AcceptTcpClient())
            using (var stream = client.GetStream())
            using (var reader = new System.IO.StreamReader(stream, Encoding.UTF8))
            using (var writer = new System.IO.StreamWriter(stream, new UTF8Encoding(false)))
            {
                writer.AutoFlush = true;
                string line = reader.ReadLine();
                if (line == null)
                {
                    writer.WriteLine("ERR empty");
                    continue;
                }
                string response = HandleCommand(line.Trim());
                writer.WriteLine(response);
                if (response == "OK quit")
                    break;
            }
        }

        listener.Stop();
        return 0;
    }

    private static string HandleCommand(string line)
    {
        if (line.Length == 0)
            return "ERR empty";

        string[] parts = line.Split(new[] { ' ', '\t' }, StringSplitOptions.RemoveEmptyEntries);
        string op = parts[0].ToLowerInvariant();

        if (op == "quit")
            return "OK quit";
        if (op == "list")
            return ListWindows();

        if (parts.Length < 3)
            return "ERR expected: <down|up|tap> <index> <key>";

        int index;
        if (!int.TryParse(parts[1], out index))
            return "ERR bad-index";

        int vk;
        if (!TryMapKey(parts[2], out vk))
            return "ERR bad-key";

        int activeIndex = -1;
        if (parts.Length >= 4)
            int.TryParse(parts[3], out activeIndex);

        var windows = FindCorporateClashWindows(activeIndex);
        if (index < 0 || index >= windows.Count)
            return "ERR no-window count=" + windows.Count;

        IntPtr hwnd = windows[index].Hwnd;
        if (op == "down")
            return PostKey(hwnd, vk, false) ? "OK down" : "ERR post-down";
        if (op == "up")
            return PostKey(hwnd, vk, true) ? "OK up" : "ERR post-up";
        if (op == "tap")
        {
            bool okDown = PostKey(hwnd, vk, false);
            System.Threading.Thread.Sleep(35);
            bool okUp = PostKey(hwnd, vk, true);
            return okDown && okUp ? "OK tap" : "ERR post-tap";
        }
        return "ERR bad-op";
    }

    private static string ListWindows()
    {
        var windows = FindCorporateClashWindows(-1);
        IntPtr foreground = GetForegroundWindow();
        var sb = new StringBuilder();
        sb.Append("OK count=").Append(windows.Count);
        for (int i = 0; i < windows.Count; i++)
        {
            var w = windows[i];
            sb.Append(" [").Append(i).Append("] hwnd=0x")
              .Append(w.Hwnd.ToInt64().ToString("x"))
              .Append(w.Hwnd == foreground ? " fg=1" : " fg=0")
              .Append(" x=").Append(w.Rect.Left)
              .Append(" title=").Append(w.Title.Replace("[", "(").Replace("]", ")"));
        }
        return sb.ToString();
    }

    private static List<GameWindow> FindCorporateClashWindows(int activeIndex)
    {
        var result = new List<GameWindow>();
        EnumWindows(delegate (IntPtr hwnd, IntPtr lParam)
        {
            if (!IsWindowVisible(hwnd))
                return true;

            var titleBuilder = new StringBuilder(512);
            int length = GetWindowTextW(hwnd, titleBuilder, titleBuilder.Capacity);
            if (length <= 0)
                return true;

            string title = titleBuilder.ToString();
            if (!title.StartsWith("Corporate Clash", StringComparison.Ordinal))
                return true;

            RECT rect;
            if (!GetWindowRect(hwnd, out rect))
                return true;
            if ((rect.Right - rect.Left) < 300 || (rect.Bottom - rect.Top) < 200)
                return true;

            result.Add(new GameWindow { Hwnd = hwnd, Title = title, Rect = rect });
            return true;
        }, IntPtr.Zero);

        result.Sort(delegate (GameWindow a, GameWindow b)
        {
            int byX = a.Rect.Left.CompareTo(b.Rect.Left);
            if (byX != 0)
                return byX;
            return a.Hwnd.ToInt64().CompareTo(b.Hwnd.ToInt64());
        });

        if (activeIndex >= 0 && activeIndex < result.Count)
        {
            IntPtr foreground = GetForegroundWindow();
            int foregroundIndex = result.FindIndex(delegate (GameWindow w) { return w.Hwnd == foreground; });
            if (foregroundIndex >= 0 && foregroundIndex != activeIndex)
            {
                GameWindow foregroundWindow = result[foregroundIndex];
                result.RemoveAt(foregroundIndex);
                if (activeIndex > result.Count)
                    activeIndex = result.Count;
                result.Insert(activeIndex, foregroundWindow);
            }
        }
        return result;
    }

    private static bool PostKey(IntPtr hwnd, int vk, bool keyUp)
    {
        bool isAlt = vk == 0x12;
        int message = keyUp
            ? (isAlt ? WM_SYSKEYUP : WM_KEYUP)
            : (isAlt ? WM_SYSKEYDOWN : WM_KEYDOWN);
        IntPtr lParam = MakeKeyLParam(vk, keyUp);
        return PostMessageW(hwnd, message, new IntPtr(vk), lParam);
    }

    private static IntPtr MakeKeyLParam(int vk, bool keyUp)
    {
        int scan = (int)(MapVirtualKeyW((uint)vk, MAPVK_VK_TO_VSC) & 0xff);
        int value = 1 | (scan << 16);
        if (IsExtendedKey(vk))
            value |= 1 << 24;
        if (keyUp)
            value |= (1 << 30) | unchecked((int)0x80000000);
        return new IntPtr(value);
    }

    private static bool IsExtendedKey(int vk)
    {
        switch (vk)
        {
            case 0x21: // PageUp
            case 0x22: // PageDown
            case 0x23: // End
            case 0x24: // Home
            case 0x25: // Left
            case 0x26: // Up
            case 0x27: // Right
            case 0x28: // Down
            case 0x2d: // Insert
            case 0x2e: // Delete
            case 0x6f: // Divide
            case 0xa3: // Right control
            case 0xa5: // Right alt
                return true;
            default:
                return false;
        }
    }

    private static bool TryMapKey(string key, out int vk)
    {
        vk = 0;
        if (key.Length == 1)
        {
            char c = char.ToUpperInvariant(key[0]);
            if (c >= 'A' && c <= 'Z')
            {
                vk = c;
                return true;
            }
            if (c >= '0' && c <= '9')
            {
                vk = c;
                return true;
            }
        }

        switch (key)
        {
            case "space": vk = 0x20; return true;
            case "Return": vk = 0x0d; return true;
            case "BackSpace": vk = 0x08; return true;
            case "Tab": vk = 0x09; return true;
            case "Escape": vk = 0x1b; return true;
            case "Delete": vk = 0x2e; return true;
            case "Up": vk = 0x26; return true;
            case "Down": vk = 0x28; return true;
            case "Left": vk = 0x25; return true;
            case "Right": vk = 0x27; return true;
            case "Shift_L":
            case "Shift_R": vk = 0x10; return true;
            case "Control_L":
            case "Control_R": vk = 0x11; return true;
            case "Alt_L":
            case "Alt_R": vk = 0x12; return true;
            case "F1": vk = 0x70; return true;
            case "F2": vk = 0x71; return true;
            case "F3": vk = 0x72; return true;
            case "F4": vk = 0x73; return true;
            case "F5": vk = 0x74; return true;
            case "F6": vk = 0x75; return true;
            case "F7": vk = 0x76; return true;
            case "F8": vk = 0x77; return true;
            case "F9": vk = 0x78; return true;
            case "F10": vk = 0x79; return true;
            case "F11": vk = 0x7a; return true;
            case "F12": vk = 0x7b; return true;
            default:
                return false;
        }
    }
}
