// Staff Directory: overlays, row selection, filters, search and the
// permissions form. Forms still submit normally; this adds the designs'
// interactive behaviour on top.
(function () {
  "use strict";

  document.documentElement.classList.add("js");

  // Dialogs ---------------------------------------------------------------

  function closeOpenMenus() {
    document.querySelectorAll("[data-menu-panel]:not([hidden])").forEach(function (panel) {
      panel.hidden = true;
      var button = panel.parentElement.querySelector("[data-menu-button]");
      if (button) button.setAttribute("aria-expanded", "false");
    });
  }

  function hiddenInput(name, value) {
    var input = document.createElement("input");
    input.type = "hidden";
    input.name = name;
    input.value = value;
    return input;
  }

  function checkedRowValues(scope) {
    return Array.prototype.map.call(
      (scope || document).querySelectorAll("[data-select-row]:checked"),
      function (box) { return box.value; }
    );
  }

  var fillers = {
    choice: function (dialog, opener) {
      var form = dialog.querySelector("[data-dialog-form]");
      form.action = opener.dataset.action || "";
      form.reset();
      if (opener.dataset.value) {
        var radio = form.querySelector('input[type=radio][value="' + opener.dataset.value + '"]');
        if (radio) radio.checked = true;
      }
      dialog.querySelectorAll("[data-fill]").forEach(function (el) {
        el.textContent = opener.dataset[el.dataset.fill] || "";
      });
    },
    suspend: function (dialog, opener) {
      var holder = dialog.querySelector("[data-suspend-ids]");
      holder.textContent = "";
      var ids = opener.dataset.ids ? [opener.dataset.ids] : checkedRowValues();
      ids.forEach(function (id) { holder.appendChild(hiddenInput("ids", id)); });
    },
    document: function (dialog, opener) {
      var frame = dialog.querySelector("[data-document-frame]");
      frame.textContent = "";
      var media;
      if (opener.dataset.pdf) {
        media = document.createElement("iframe");
        media.title = "Identity document for " + (opener.dataset.name || "staff member");
      } else {
        media = document.createElement("img");
        media.alt = "Identity document for " + (opener.dataset.name || "staff member");
      }
      media.src = opener.dataset.src;
      frame.appendChild(media);
    },
    invite: function (dialog, opener) {
      var data = opener.dataset;
      dialog.querySelectorAll("[data-fill]").forEach(function (el) {
        el.textContent = data[el.dataset.fill] || "";
      });
      var status = dialog.querySelector("[data-status-class]");
      status.className = "detail-status detail-status--" + (data.statusValue || "");
      var pill = dialog.querySelector("[data-role-class]");
      pill.className = "role-pill-sm role-pill-sm--" + (data.inviterRoleValue || "");
      pill.hidden = !data.inviterRole;
      [["[data-invite-revoke]", data.revoke], ["[data-invite-resend]", data.resend]].forEach(function (pair) {
        var form = dialog.querySelector(pair[0]);
        form.action = pair[1] || "";
        form.hidden = !pair[1];
      });
    },
  };

  function fillerFor(dialog) {
    if (dialog.hasAttribute("data-choice-dialog")) return fillers.choice;
    if (dialog.hasAttribute("data-suspend-dialog")) return fillers.suspend;
    if (dialog.hasAttribute("data-document-dialog")) return fillers.document;
    if (dialog.hasAttribute("data-invite-dialog")) return fillers.invite;
    return null;
  }

  function openDialog(dialog, opener) {
    if (!dialog || typeof dialog.showModal !== "function") return;
    closeOpenMenus();
    var fill = fillerFor(dialog);
    if (fill && opener) fill(dialog, opener);
    dialog.showModal();
  }

  document.querySelectorAll("[data-dialog-open]").forEach(function (opener) {
    opener.addEventListener("click", function (event) {
      event.stopPropagation();
      openDialog(document.getElementById(opener.dataset.dialogOpen), opener);
    });
  });

  document.querySelectorAll("dialog.modal").forEach(function (dialog) {
    dialog.querySelectorAll("[data-dialog-close]").forEach(function (button) {
      button.addEventListener("click", function () { dialog.close(); });
    });
    // A click on the backdrop lands on the dialog element itself.
    dialog.addEventListener("click", function (event) {
      if (event.target === dialog) dialog.close();
    });
    dialog.addEventListener("close", function () {
      var frame = dialog.querySelector("[data-document-frame]");
      if (frame) frame.textContent = "";
    });
    if (dialog.hasAttribute("data-open-on-load")) openDialog(dialog);
  });

  // Flash messages ------------------------------------------------------------

  document.querySelectorAll("[data-flash-close]").forEach(function (button) {
    button.addEventListener("click", function () { button.closest(".flash").remove(); });
  });

  // Row selection -----------------------------------------------------------

  document.querySelectorAll("[data-selectable-panel]").forEach(function (panel) {
    var all = panel.querySelector("[data-select-all]");
    var rows = panel.querySelectorAll("[data-select-row]");
    var bar = panel.querySelector("[data-selection-bar]");
    if (!rows.length || !bar) return;
    var count = bar.querySelector("[data-selection-count]");

    function sync() {
      var selected = 0;
      rows.forEach(function (box) {
        box.closest("tr").classList.toggle("is-selected", box.checked);
        if (box.checked) selected++;
      });
      count.textContent = selected;
      bar.hidden = selected === 0;
      if (all) {
        all.checked = selected === rows.length;
        all.indeterminate = selected > 0 && selected < rows.length;
      }
    }

    rows.forEach(function (box) { box.addEventListener("change", sync); });
    if (all) {
      all.addEventListener("change", function () {
        rows.forEach(function (box) { box.checked = all.checked; });
        sync();
      });
    }
    bar.querySelector("[data-selection-clear]").addEventListener("click", function () {
      rows.forEach(function (box) { box.checked = false; });
      sync();
    });

    if (bar.hasAttribute("data-bulk-form")) {
      bar.addEventListener("submit", function () {
        var holder = bar.querySelector("[data-bulk-ids]");
        holder.textContent = "";
        checkedRowValues(panel).forEach(function (id) { holder.appendChild(hiddenInput("ids", id)); });
      });
    }
    sync();
  });

  // Search, filters and loading state -----------------------------------------

  function showLoading(form) {
    var region = form.closest("[data-selectable-panel], .panel").querySelector("[data-loading-region]");
    if (!region) return;
    region.textContent = "";
    var loading = document.createElement("div");
    loading.className = "loading-row";
    loading.setAttribute("role", "status");
    loading.innerHTML = '<span class="spinner" aria-hidden="true"></span>Loading..';
    region.appendChild(loading);
    for (var i = 0; i < 8; i++) {
      var row = document.createElement("div");
      row.className = "skeleton-row";
      row.setAttribute("aria-hidden", "true");
      row.innerHTML = '<span class="skeleton-box"></span><span class="skeleton-circle"></span>';
      region.appendChild(row);
    }
  }

  function submitWithLoading(form) {
    showLoading(form);
    if (typeof form.requestSubmit === "function") form.requestSubmit();
    else form.submit();
  }

  document.querySelectorAll("[data-filter-form]").forEach(function (form) {
    var timer = null;
    var search = form.querySelector("[data-search-input]");

    form.addEventListener("submit", function () {
      form.querySelectorAll("[data-filter-all]").forEach(function (box) { box.disabled = true; });
    });

    if (search) {
      try {
        if (window.sessionStorage.getItem("phogbs.searchFocus") === "1") {
          window.sessionStorage.removeItem("phogbs.searchFocus");
          search.focus();
          var length = search.value.length;
          search.setSelectionRange(length, length);
        }
      } catch (e) { /* storage unavailable */ }

      search.addEventListener("input", function () {
        clearTimeout(timer);
        timer = setTimeout(function () {
          try { window.sessionStorage.setItem("phogbs.searchFocus", "1"); } catch (e) { /* ignore */ }
          submitWithLoading(form);
        }, 450);
      });
    }

    form.querySelectorAll("[data-filter-menu]").forEach(function (menu) {
      var categories = menu.querySelectorAll("[data-filter-category]");
      var groups = menu.querySelectorAll("[data-filter-group]");

      categories.forEach(function (category) {
        var select = function () {
          categories.forEach(function (c) {
            var selected = c === category;
            c.classList.toggle("is-selected", selected);
            c.setAttribute("aria-selected", String(selected));
          });
          groups.forEach(function (group) {
            group.hidden = group.id !== category.getAttribute("aria-controls");
          });
        };
        category.addEventListener("click", select);
        category.addEventListener("mouseenter", select);
      });

      groups.forEach(function (group) {
        var allBox = group.querySelector("[data-filter-all]");
        var boxes = group.querySelectorAll("input[name]");
        allBox.addEventListener("change", function () {
          if (allBox.checked) boxes.forEach(function (box) { box.checked = false; });
          else if (!Array.prototype.some.call(boxes, function (b) { return b.checked; })) allBox.checked = true;
          schedule();
        });
        boxes.forEach(function (box) {
          box.addEventListener("change", function () {
            var any = Array.prototype.some.call(boxes, function (b) { return b.checked; });
            allBox.checked = !any;
            schedule();
          });
        });
      });

      function schedule() {
        clearTimeout(timer);
        timer = setTimeout(function () { submitWithLoading(form); }, 350);
      }
    });
  });

  // Add Staff form ------------------------------------------------------------

  document.querySelectorAll("[data-add-staff-form]").forEach(function (form) {
    var email = form.querySelector("input[name=email]");
    var role = form.querySelector("select[name=role]");
    var orgField = form.querySelector("[data-organisation-field]");
    var submit = form.querySelector("[data-require-filled]");
    function sync() {
      orgField.hidden = role.value !== "corporate_admin";
      submit.disabled = !email.value.trim() || !role.value;
    }
    email.addEventListener("input", sync);
    role.addEventListener("change", sync);
    sync();
  });

  // Roles & permissions ---------------------------------------------------------

  document.querySelectorAll("[data-permission-form]").forEach(function (form) {
    var bar = form.querySelector("[data-save-bar]");
    if (!bar) return;
    var status = bar.querySelector("[data-save-status]");
    var dirty = false;
    form.addEventListener("change", function () {
      dirty = true;
      bar.classList.add("is-dirty");
      status.textContent = "You have unsaved changes.";
    });
    form.addEventListener("submit", function () { dirty = false; });
    window.addEventListener("beforeunload", function (event) {
      if (dirty) {
        event.preventDefault();
        event.returnValue = "";
      }
    });
  });
})();
