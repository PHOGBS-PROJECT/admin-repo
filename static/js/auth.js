// Progressive enhancement for the sign-in and account setup screens.
// Every form still works without this script; it adds the design's
// interactive states (disabled buttons, "Submitting…", live password
// checks, drag-and-drop upload with progress).
(function () {
  "use strict";

  function csrfToken(form) {
    var input = form.querySelector("input[name=csrfmiddlewaretoken]");
    return input ? input.value : "";
  }

  // Show / hide password
  document.querySelectorAll("[data-password-toggle]").forEach(function (button) {
    var input = document.getElementById(button.getAttribute("aria-controls"));
    if (!input) return;
    button.addEventListener("click", function () {
      var show = input.type === "password";
      input.type = show ? "text" : "password";
      button.setAttribute("aria-pressed", String(show));
      button.setAttribute("aria-label", show ? "Hide password" : "Show password");
    });
  });

  // Submit states
  document.querySelectorAll("[data-auth-form]").forEach(function (form) {
    var submit = form.querySelector("button[type=submit]");
    if (!submit) return;

    if (form.hasAttribute("data-require-filled")) {
      var required = form.querySelectorAll("input[required]");
      var sync = function () {
        submit.disabled = Array.prototype.some.call(required, function (input) {
          return !input.value.trim();
        });
      };
      required.forEach(function (input) {
        input.addEventListener("input", sync);
      });
      sync();
    }

    form.addEventListener("submit", function (event) {
      if (form.dataset.submitting === "true" || form.dataset.busy === "true") {
        event.preventDefault();
        return;
      }
      form.dataset.submitting = "true";
      form.querySelectorAll(".status-area .status:not([data-pending-status])").forEach(function (el) {
        el.hidden = true;
      });
      var pending = form.querySelector("[data-pending-status]");
      if (pending) pending.hidden = false;
      submit.setAttribute("aria-disabled", "true");
    });

    // Restore the form if the user comes back with the Back button.
    window.addEventListener("pageshow", function (event) {
      if (!event.persisted) return;
      form.dataset.submitting = "false";
      submit.removeAttribute("aria-disabled");
      var pending = form.querySelector("[data-pending-status]");
      if (pending) pending.hidden = true;
    });
  });

  // Live password checklist (mirrors apps/accounts/validators.py)
  var PASSWORD_RULES = {
    length: function (p) { return p.length >= 12; },
    upper: function (p) { return /[A-Z]/.test(p); },
    lower: function (p) { return /[a-z]/.test(p); },
    number_or_symbol: function (p) { return /[^A-Za-z]/.test(p); },
  };

  document.querySelectorAll("[data-password-rules]").forEach(function (list) {
    var input = document.getElementById(list.dataset.for);
    if (!input) return;
    var update = function () {
      var value = input.value;
      list.querySelectorAll("[data-rule]").forEach(function (item) {
        var met = PASSWORD_RULES[item.dataset.rule](value);
        item.classList.toggle("is-met", value !== "" && met);
        item.classList.toggle("is-unmet", value !== "" && !met);
      });
    };
    input.addEventListener("input", update);
    update();
  });

  // Identity method, number and name lookup
  document.querySelectorAll("[data-identity-form]").forEach(function (form) {
    var radios = form.querySelectorAll("input[name=identity_method]");
    var numberField = form.querySelector("[data-identity-number]");
    var label = form.querySelector("[data-identity-label]");
    var input = numberField.querySelector("input");
    var nameEl = form.querySelector("[data-identity-name]");
    var lookupUrl = form.dataset.lookupUrl;
    var lookupController = null;
    var lastLookup = "";

    function selectedMethod() {
      var checked = form.querySelector("input[name=identity_method]:checked");
      return checked ? checked.value : "";
    }

    function clearName() {
      nameEl.hidden = true;
      nameEl.textContent = "";
    }

    function syncMethod() {
      var method = selectedMethod();
      numberField.hidden = !method;
      if (!method) return;
      var short = method.toUpperCase();
      label.textContent = "Enter your " + short;
      input.placeholder = "Enter your 11-digit " + short;
    }

    function lookup() {
      var method = selectedMethod();
      var number = input.value;
      if (!method || number.length !== 11) {
        clearName();
        lastLookup = "";
        return;
      }
      var key = method + ":" + number;
      if (key === lastLookup) return;
      lastLookup = key;
      if (lookupController) lookupController.abort();
      lookupController = new AbortController();
      fetch(lookupUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken(form) },
        body: JSON.stringify({ method: method, number: number }),
        credentials: "same-origin",
        signal: lookupController.signal,
      })
        .then(function (response) { return response.ok ? response.json() : null; })
        .then(function (data) {
          if (data && data.name) {
            nameEl.textContent = data.name;
            nameEl.hidden = false;
          } else {
            clearName();
          }
        })
        .catch(function () { /* lookup is a convenience; ignore failures */ });
    }

    radios.forEach(function (radio) {
      radio.addEventListener("change", function () {
        syncMethod();
        lastLookup = "";
        lookup();
      });
    });

    input.addEventListener("input", function () {
      var digits = input.value.replace(/\D/g, "").slice(0, 11);
      if (digits !== input.value) input.value = digits;
      lookup();
    });

    syncMethod();
    lookup();
  });

  // Identity document upload
  document.querySelectorAll("[data-upload]").forEach(function (zone) {
    var form = zone.closest("form");
    var fileInput = zone.querySelector("input[type=file]");
    var url = zone.dataset.uploadUrl;
    var maxBytes = parseInt(zone.dataset.maxBytes, 10);
    var errorEl = form.querySelector("[data-upload-error]");
    var percentEl = zone.querySelector("[data-upload-percent]");
    var progress = zone.querySelector("[data-upload-progress]");
    var bar = progress.querySelector("span");
    var badge = zone.querySelector("[data-upload-badge]");
    var allowed = ["png", "jpg", "jpeg", "gif", "pdf"];

    function setState(state) {
      zone.classList.toggle("upload--progress", state === "progress");
      zone.classList.toggle("upload--done", state === "done");
      form.dataset.busy = state === "progress" ? "true" : "false";
    }

    function showError(message) {
      errorEl.textContent = message;
      errorEl.hidden = !message;
    }

    function setFilename(name) {
      zone.querySelectorAll("[data-upload-filename]").forEach(function (el) {
        el.textContent = name;
      });
    }

    function setProgress(percent) {
      percentEl.textContent = percent + "%";
      bar.style.width = percent + "%";
      progress.setAttribute("aria-valuenow", String(percent));
    }

    function upload(file) {
      showError("");
      var extension = (file.name.split(".").pop() || "").toLowerCase();
      if (allowed.indexOf(extension) === -1) {
        showError("Upload a PNG, JPG, GIF or PDF file.");
        return;
      }
      if (file.size > maxBytes) {
        showError("The file is too large. The maximum size is " + Math.round(maxBytes / 1048576) + " MB.");
        return;
      }

      var data = new FormData();
      data.append("document", file);
      var xhr = new XMLHttpRequest();
      xhr.open("POST", url);
      xhr.setRequestHeader("X-CSRFToken", csrfToken(form));
      xhr.upload.addEventListener("progress", function (event) {
        if (event.lengthComputable) setProgress(Math.round((event.loaded / event.total) * 100));
      });
      xhr.addEventListener("load", function () {
        fileInput.value = "";
        if (xhr.status === 201) {
          setState("done");
          return;
        }
        setState("empty");
        var message = "We couldn't upload this file. Please try again.";
        try {
          var body = JSON.parse(xhr.responseText);
          if (body.document && body.document[0]) message = body.document[0];
          else if (body.detail) message = body.detail;
        } catch (e) { /* keep default message */ }
        showError(message);
      });
      xhr.addEventListener("error", function () {
        fileInput.value = "";
        setState("empty");
        showError("We couldn't upload this file. Check your connection and try again.");
      });

      badge.textContent = extension === "jpeg" ? "JPG" : extension.toUpperCase();
      setFilename(file.name);
      setProgress(0);
      setState("progress");
      xhr.send(data);
    }

    fileInput.addEventListener("change", function () {
      if (fileInput.files.length) upload(fileInput.files[0]);
    });

    ["dragenter", "dragover"].forEach(function (type) {
      zone.addEventListener(type, function (event) {
        event.preventDefault();
        zone.classList.add("is-dragover");
      });
    });
    ["dragleave", "drop"].forEach(function (type) {
      zone.addEventListener(type, function (event) {
        event.preventDefault();
        zone.classList.remove("is-dragover");
      });
    });
    zone.addEventListener("drop", function (event) {
      var files = event.dataTransfer && event.dataTransfer.files;
      if (files && files.length) upload(files[0]);
    });

    zone.querySelector("[data-upload-clear]").addEventListener("click", function () {
      fetch(url, {
        method: "DELETE",
        headers: { "X-CSRFToken": csrfToken(form) },
        credentials: "same-origin",
      }).then(function (response) {
        if (response.ok) {
          setFilename("");
          setState("empty");
          showError("");
        } else {
          showError("We couldn't remove the file. Please try again.");
        }
      }).catch(function () {
        showError("We couldn't remove the file. Check your connection and try again.");
      });
    });
  });
})();
