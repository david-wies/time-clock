"""Tests for views/record_tab_common.py's RecordTabMixin.

RecordTabMixin is Tk-free enough (per its own docstring, shared by
TimeClockTab/VacationTab/SicknessTab/MiliuimTab) that every method here can
be exercised with plain ``unittest.mock.Mock`` stand-ins for the widgets it
operates on (``_tree``, ``_btn_edit``, ``_btn_delete``, ``_var_year``,
``_var_month``) -- no live Tk interpreter/display needed, unlike most of the
rest of views/ (see tests/views/test_time_clock_tab_pure.py for the same
headless-CI constraint on other view modules). Only ``_guard_visible`` reads
``self.winfo_exists()``/``self.winfo_ismapped()``, which are likewise mocked
on the test double rather than backed by a real widget.
"""

import logging
import tkinter as tk
from typing import Any
from unittest import mock

from views.record_tab_common import RecordTabMixin


class _FakeMixinHost(RecordTabMixin):
    """Minimal stand-in providing the attributes/hooks RecordTabMixin needs.

    ``root`` is a plain ``mock.Mock`` standing in for the shared Tk root
    widget: ``_bind_shortcut``/``_clear_shortcuts`` only ever call
    ``root.bind_all``/``root.unbind`` on it, so a Mock records those calls
    without needing a live Tk interpreter, matching how ``_tree`` etc. are
    faked below.
    """

    def __init__(self) -> None:
        # Explicit `mock.Mock` annotations override the `ttk.Treeview` /
        # `tk.StringVar` types RecordTabMixin declares for these attributes
        # -- without them, a static type checker holds the base class's
        # declared type here and rejects `.return_value` assignments on
        # `.selection`/`.get`/etc. below as not existing on the real widget
        # method.
        self._tree: mock.Mock = mock.Mock()
        self._btn_edit: mock.Mock = mock.Mock()
        self._btn_delete: mock.Mock = mock.Mock()
        self._var_year: mock.Mock = mock.Mock()
        self._var_month: mock.Mock = mock.Mock()
        self._selected_year = 0
        self._selected_month = 0
        self._unsubs: list[Any] = []
        self.refresh_called = False
        self.edit_called = False
        self.winfo_exists: mock.Mock = mock.Mock(return_value=True)
        self.winfo_ismapped: mock.Mock = mock.Mock(return_value=True)
        self.root: mock.Mock = mock.Mock()

    def _refresh(self, **_kw: object) -> None:
        self.refresh_called = True

    def _do_edit(self) -> None:
        self.edit_called = True


# --- _get_selected_record_id -------------------------------------------------


def test_get_selected_record_id_returns_none_when_no_selection() -> None:
    host = _FakeMixinHost()
    host._tree.selection.return_value = ()

    assert host._get_selected_record_id() is None


def test_get_selected_record_id_parses_valid_iid() -> None:
    host = _FakeMixinHost()
    host._tree.selection.return_value = ("rec_5",)

    assert host._get_selected_record_id() == 5


def test_get_selected_record_id_returns_none_for_malformed_iid() -> None:
    host = _FakeMixinHost()
    host._tree.selection.return_value = ("rec_abc",)

    assert host._get_selected_record_id() is None


def test_get_selected_record_id_returns_none_for_non_rec_prefixed_iid() -> None:
    host = _FakeMixinHost()
    host._tree.selection.return_value = ("other_1",)

    assert host._get_selected_record_id() is None


# --- _update_edit_delete_states / _update_button_states ----------------------


def test_update_edit_delete_states_enables_buttons_when_selected() -> None:
    host = _FakeMixinHost()
    host._tree.selection.return_value = ("rec_1",)

    host._update_edit_delete_states()

    host._btn_edit.config.assert_called_once_with(state="normal")
    host._btn_delete.config.assert_called_once_with(state="normal")


def test_update_edit_delete_states_disables_buttons_when_not_selected() -> None:
    host = _FakeMixinHost()
    host._tree.selection.return_value = ()

    host._update_edit_delete_states()

    host._btn_edit.config.assert_called_once_with(state="disabled")
    host._btn_delete.config.assert_called_once_with(state="disabled")


def test_update_button_states_delegates_to_update_edit_delete_states() -> None:
    host = _FakeMixinHost()
    with mock.patch.object(host, "_update_edit_delete_states") as spy:
        host._update_button_states()

    spy.assert_called_once_with()


# --- _on_double_click ---------------------------------------------------------


def test_on_double_click_on_record_row_selects_and_edits() -> None:
    host = _FakeMixinHost()
    host._tree.identify_row.return_value = "rec_7"
    event = mock.Mock(y=42)

    host._on_double_click(event)

    host._tree.identify_row.assert_called_once_with(42)
    host._tree.selection_set.assert_called_once_with("rec_7")
    assert host.edit_called is True


def test_on_double_click_on_empty_row_does_nothing() -> None:
    host = _FakeMixinHost()
    host._tree.identify_row.return_value = ""
    event = mock.Mock(y=42)

    host._on_double_click(event)

    host._tree.selection_set.assert_not_called()
    assert host.edit_called is False


def test_on_double_click_on_non_rec_row_does_nothing() -> None:
    host = _FakeMixinHost()
    host._tree.identify_row.return_value = "header"
    event = mock.Mock(y=42)

    host._on_double_click(event)

    host._tree.selection_set.assert_not_called()
    assert host.edit_called is False


# --- _on_tree_select -----------------------------------------------------------


def test_on_tree_select_delegates_to_update_edit_delete_states() -> None:
    host = _FakeMixinHost()
    with mock.patch.object(host, "_update_edit_delete_states") as spy:
        host._on_tree_select(None)

    spy.assert_called_once_with()


# --- _on_period_changed --------------------------------------------------------


def test_on_period_changed_all_months_sets_zero_and_refreshes() -> None:
    host = _FakeMixinHost()
    host._var_year.get.return_value = "2026"
    host._var_month.get.return_value = "All"

    host._on_period_changed(None)

    assert host._selected_year == 2026
    assert host._selected_month == 0
    assert host.refresh_called is True


def test_on_period_changed_real_month_sets_one_based_index() -> None:
    host = _FakeMixinHost()
    host._var_year.get.return_value = "2026"
    host._var_month.get.return_value = "March"

    host._on_period_changed(None)

    assert host._selected_year == 2026
    assert host._selected_month == 3
    assert host.refresh_called is True


def test_on_period_changed_invalid_year_does_not_refresh_or_raise(caplog) -> None:
    host = _FakeMixinHost()
    host._var_year.get.return_value = "abc"
    host._var_month.get.return_value = "All"

    with caplog.at_level(logging.ERROR, logger="views.record_tab_common"):
        host._on_period_changed(None)  # must not raise

    assert host.refresh_called is False
    assert host._selected_year == 0  # unchanged from initial value


def test_on_period_changed_unrecognized_month_leaves_month_unchanged() -> None:
    """Pins the mixin's current no-`else` fallthrough: an unrecognized month
    name (not "All", not in MONTH_NAMES) leaves _selected_month untouched --
    this is a real gap a prior review flagged, not necessarily desired
    behavior, but this test documents what the code actually does today."""
    host = _FakeMixinHost()
    host._selected_month = 99  # sentinel prior value
    host._var_year.get.return_value = "2026"
    host._var_month.get.return_value = "NotAMonth"

    host._on_period_changed(None)

    assert host._selected_year == 2026
    assert host._selected_month == 99  # unchanged
    assert host.refresh_called is True


# --- _append_skip_notice --------------------------------------------------------


def test_append_skip_notice_noops_when_skipped_is_zero() -> None:
    label = mock.Mock()

    RecordTabMixin._append_skip_notice(label, 0)

    label.config.assert_not_called()


def test_append_skip_notice_noops_when_skipped_is_negative() -> None:
    label = mock.Mock()

    RecordTabMixin._append_skip_notice(label, -1)

    label.config.assert_not_called()


def test_append_skip_notice_sets_bare_notice_when_label_empty() -> None:
    label = mock.Mock()
    label.cget.return_value = ""

    RecordTabMixin._append_skip_notice(label, 3)

    label.config.assert_called_once_with(
        text="(3 record(s) skipped due to data errors)"
    )


def test_append_skip_notice_appends_to_existing_text() -> None:
    label = mock.Mock()
    label.cget.return_value = "Balance: 10h"

    RecordTabMixin._append_skip_notice(label, 2)

    label.config.assert_called_once_with(
        text="Balance: 10h  (2 record(s) skipped due to data errors)"
    )


# --- _clear_unsubs --------------------------------------------------------------


def test_clear_unsubs_calls_all_and_isolates_failures(caplog) -> None:
    host = _FakeMixinHost()
    good1 = mock.Mock()
    bad = mock.Mock(side_effect=RuntimeError("boom"))
    good2 = mock.Mock()
    host._unsubs = [good1, bad, good2]

    with caplog.at_level(logging.ERROR, logger="views.record_tab_common"):
        host._clear_unsubs()  # must not raise

    good1.assert_called_once_with()
    bad.assert_called_once_with()
    good2.assert_called_once_with()
    assert host._unsubs == []


def test_clear_unsubs_with_no_subscriptions_is_a_noop() -> None:
    host = _FakeMixinHost()
    host._unsubs = []

    host._clear_unsubs()

    assert host._unsubs == []


# --- _bind_shortcut -------------------------------------------------------------


def test_bind_shortcut_calls_root_bind_all_and_records_binding() -> None:
    host = _FakeMixinHost()
    host.root.bind_all.return_value = "funcid-1"
    handler = mock.Mock()

    host._bind_shortcut("<Control-s>", handler)

    call_args = host.root.bind_all.call_args
    assert call_args.args[0] == "<Control-s>"
    assert callable(call_args.args[1])
    assert call_args.kwargs == {"add": True}
    assert host._shortcut_binds == [("<Control-s>", "funcid-1")]


def test_bind_shortcut_wraps_handler_with_guard_visible() -> None:
    """The callable passed to ``bind_all`` must be the ``_guard_visible``
    wrapper around ``handler``, not ``handler`` itself -- otherwise the
    shortcut would fire even while this tab is hidden behind another one in
    the Notebook."""
    host = _FakeMixinHost()
    host.root.bind_all.return_value = "funcid-1"
    handler = mock.Mock()

    host._bind_shortcut("<Control-s>", handler)
    wrapped = host.root.bind_all.call_args.args[1]
    assert wrapped is not handler

    wrapped(None)
    handler.assert_called_once_with()

    handler.reset_mock()
    host.winfo_ismapped.return_value = False
    wrapped(None)
    handler.assert_not_called()


def test_bind_shortcut_appends_across_multiple_calls() -> None:
    host = _FakeMixinHost()
    host.root.bind_all.side_effect = ["fid-1", "fid-2"]

    host._bind_shortcut("<Control-s>", mock.Mock())
    host._bind_shortcut("<Control-p>", mock.Mock())

    assert host._shortcut_binds == [
        ("<Control-s>", "fid-1"),
        ("<Control-p>", "fid-2"),
    ]


# --- _clear_shortcuts -------------------------------------------------------------


def test_clear_shortcuts_unbinds_each_binding_by_funcid_not_unbind_all() -> None:
    """Must use ``root.unbind(sequence, funcid)`` per-binding, never
    ``root.unbind_all(sequence)`` -- the latter would strip bindings that
    other tab instances sharing this root registered via ``add=True`` on the
    same key sequence."""
    host = _FakeMixinHost()
    host._shortcut_binds = [("<Control-s>", "fid-1"), ("<Control-p>", "fid-2")]

    host._clear_shortcuts()

    host.root.unbind.assert_has_calls(
        [mock.call("<Control-s>", "fid-1"), mock.call("<Control-p>", "fid-2")]
    )
    host.root.unbind_all.assert_not_called()
    assert host._shortcut_binds == []


def test_clear_shortcuts_calls_all_and_isolates_failures(caplog) -> None:
    host = _FakeMixinHost()
    host._shortcut_binds = [
        ("<Control-s>", "fid-1"),
        ("<Control-p>", "fid-2"),
        ("<Control-z>", "fid-3"),
    ]
    host.root.unbind.side_effect = [None, RuntimeError("boom"), None]

    with caplog.at_level(logging.ERROR, logger="views.record_tab_common"):
        host._clear_shortcuts()  # must not raise

    assert host.root.unbind.call_count == 3
    assert host._shortcut_binds == []


def test_clear_shortcuts_with_no_bindings_is_a_noop() -> None:
    host = _FakeMixinHost()

    host._clear_shortcuts()

    host.root.unbind.assert_not_called()
    assert host._shortcut_binds == []


# --- _on_destroy ------------------------------------------------------------------


def test_on_destroy_clears_unsubs() -> None:
    host = _FakeMixinHost()
    unsub = mock.Mock()
    host._unsubs = [unsub]

    host._on_destroy(None)

    unsub.assert_called_once_with()
    assert host._unsubs == []


def test_on_destroy_clears_shortcuts() -> None:
    host = _FakeMixinHost()
    host._shortcut_binds = [("<Control-s>", "fid-1")]

    host._on_destroy(None)

    host.root.unbind.assert_called_once_with("<Control-s>", "fid-1")
    assert host._shortcut_binds == []


def test_on_destroy_delegates_to_clear_unsubs() -> None:
    host = _FakeMixinHost()
    with mock.patch.object(host, "_clear_unsubs") as spy:
        host._on_destroy(None)

    spy.assert_called_once_with()


def test_on_destroy_delegates_to_clear_shortcuts() -> None:
    host = _FakeMixinHost()
    with mock.patch.object(host, "_clear_shortcuts") as spy:
        host._on_destroy(None)

    spy.assert_called_once_with()


# --- _guard_visible -----------------------------------------------------------------


def test_guard_visible_calls_fn_when_visible() -> None:
    host = _FakeMixinHost()
    fn = mock.Mock()
    handler = host._guard_visible(fn)

    handler(None)

    fn.assert_called_once_with()


def test_guard_visible_skips_fn_when_not_exists() -> None:
    host = _FakeMixinHost()
    host.winfo_exists.return_value = False
    fn = mock.Mock()
    handler = host._guard_visible(fn)

    handler(None)

    fn.assert_not_called()


def test_guard_visible_skips_fn_when_not_mapped() -> None:
    host = _FakeMixinHost()
    host.winfo_ismapped.return_value = False
    fn = mock.Mock()
    handler = host._guard_visible(fn)

    handler(None)

    fn.assert_not_called()


def test_guard_visible_swallows_tclerror_from_winfo_exists() -> None:
    host = _FakeMixinHost()
    host.winfo_exists.side_effect = tk.TclError("destroyed")
    fn = mock.Mock()
    handler = host._guard_visible(fn)

    handler(None)  # must not raise

    fn.assert_not_called()


def test_guard_visible_swallows_tclerror_from_fn() -> None:
    host = _FakeMixinHost()
    fn = mock.Mock(side_effect=tk.TclError("widget gone mid-call"))
    handler = host._guard_visible(fn)

    handler(None)  # must not raise

    fn.assert_called_once_with()
