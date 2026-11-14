import time

from mytts.capture import KEYEVENTF_EXTENDEDKEY, VK_C, VK_INSERT, VK_MENU, capture_selection, copy_key

OLD = [("text", "what the user copied earlier"), ("image", b"\x89PNG")]


class FakeSystem:
    """A clipboard plus an app that copies its selection a few polls after Ctrl+C."""

    def __init__(self, selection="Read me.", copy_after=2, held_polls=0, busy_polls=0, held=(VK_MENU,)):
        self.selection = selection  # str (text), bytes (non-text) or None (nothing selected)
        self.copy_after = copy_after
        self.held_polls = held_polls
        self.busy_polls = busy_polls
        self.held = list(held)
        self.seq = 10
        self.clip = list(OLD)
        self.pending = None
        self.sent = []
        self.restored = 0

    def modifiers_down(self):
        if self.held_polls > 0:
            self.held_polls -= 1
            return self.held
        return []

    def sequence(self):
        if self.pending is not None:
            self.pending -= 1
            if self.pending <= 0:
                self.pending = None
                self.seq += 1
                kind = "text" if isinstance(self.selection, str) else "image"
                self.clip = [(kind, self.selection)]
        return self.seq

    def snapshot(self):
        return list(self.clip)

    def restore(self, saved):
        self.clip = list(saved)
        self.seq += 1
        self.restored += 1

    def read_text(self):
        if self.busy_polls > 0:  # the app still has the clipboard open
            self.busy_polls -= 1
            return None
        return dict(self.clip).get("text")

    def send_copy(self, still_held):
        self.sent.append(list(still_held))
        if self.selection is not None:
            self.pending = self.copy_after


def run(fake, **kw):
    kw.setdefault("modifier_wait", 0.5)
    kw.setdefault("copy_wait", 0.3)
    return capture_selection(system=fake, **kw)


def test_reads_selection_and_restores_clipboard():
    fake = FakeSystem()
    assert run(fake) == "Read me."
    assert fake.clip == OLD and fake.restored == 1
    assert fake.sent == [[]]


def test_keeps_selection_on_clipboard_when_restore_is_off():
    fake = FakeSystem()
    assert run(fake, restore=False) == "Read me."
    assert fake.clip == [("text", "Read me.")] and fake.restored == 0


def test_nothing_selected_leaves_clipboard_alone():
    fake = FakeSystem(selection=None)
    t0 = time.monotonic()
    assert run(fake, copy_wait=0.1) is None
    assert time.monotonic() - t0 >= 0.1
    assert fake.clip == OLD and fake.restored == 0


def test_waits_for_modifiers_to_be_released():
    fake = FakeSystem(held_polls=3)
    assert run(fake) == "Read me."
    assert fake.sent == [[]]  # released in time: plain Ctrl+C


def test_still_held_modifiers_are_passed_on():
    fake = FakeSystem(held_polls=10_000)
    t0 = time.monotonic()
    assert run(fake, modifier_wait=0.05) == "Read me."
    assert time.monotonic() - t0 < 0.3
    assert fake.sent == [[VK_MENU]]


def test_copied_something_without_text():
    fake = FakeSystem(selection=b"pixels")
    assert run(fake, copy_wait=0.1) == ""
    assert fake.clip == OLD and fake.restored == 1


def test_clipboard_busy_right_after_the_copy():
    fake = FakeSystem(busy_polls=3)
    assert run(fake) == "Read me."
    assert fake.clip == OLD


def test_terminals_get_ctrl_insert():
    # Ctrl+C with nothing selected would interrupt the program running in a terminal.
    assert copy_key("CASCADIA_HOSTING_WINDOW_CLASS") == (VK_INSERT, KEYEVENTF_EXTENDEDKEY)
    assert copy_key("ConsoleWindowClass") == (VK_INSERT, KEYEVENTF_EXTENDEDKEY)
    assert copy_key("mintty") == (VK_INSERT, KEYEVENTF_EXTENDEDKEY)
    assert copy_key("Chrome_WidgetWin_1") == (VK_C, 0)
    assert copy_key("") == (VK_C, 0)
