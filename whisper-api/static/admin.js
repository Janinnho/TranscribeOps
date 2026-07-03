const AdminUI = (() => {
  async function api(path, opts = {}) {
    const res = await fetch(path, {
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      ...opts,
    });
    if (!res.ok) {
      let err;
      try { err = await res.json(); } catch { err = { error: res.statusText }; }
      throw new Error(err.error || `HTTP ${res.status}`);
    }
    return res.json();
  }

  // ----- API Keys -----
  function wireKeyActions() {
    document.querySelectorAll('[data-action="revoke"]').forEach(btn => {
      btn.addEventListener("click", async () => {
        const id = btn.dataset.id;
        if (!confirm(window.tr("Really revoke this key?"))) return;
        await api(`/admin/api/keys/${id}`, { method: "DELETE" });
        location.reload();
      });
    });
  }

  function wireNewKeyForm() {
    const form = document.getElementById("new-key-form");
    if (!form) return;
    form.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const label = form.label.value.trim();
      const res = await api("/admin/api/keys", {
        method: "POST",
        body: JSON.stringify({ label }),
      });
      const box = document.getElementById("new-key-result");
      document.getElementById("new-key-raw").textContent = res.raw_key;
      box.classList.remove("hidden");
      form.label.value = "";
      setTimeout(() => location.reload(), 8000);
    });
  }

  // ----- Downloads -----
  function wireDownloadButtons() {
    document.querySelectorAll(".download-btn").forEach(btn => {
      btn.addEventListener("click", async () => {
        const repo_id = btn.dataset.repo;
        const kind = btn.dataset.kind;
        btn.disabled = true;
        btn.textContent = window.tr("Starting…");
        try {
          const res = await api("/admin/api/downloads", {
            method: "POST",
            body: JSON.stringify({ repo_id, kind }),
          });
          pollDownload(res.id, btn.closest("tr"));
        } catch (e) {
          btn.disabled = false;
          btn.textContent = window.tr("Download");
          alert(window.tr("Download failed: {msg}", {msg: e.message}));
        }
      });
    });
  }

  function wireCustomDownloadForm() {
    const form = document.getElementById("custom-dl-form");
    if (!form) return;
    form.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const repo_id = form.repo_id.value.trim();
      const kind = form.kind.value;
      try {
        await api("/admin/api/downloads", {
          method: "POST",
          body: JSON.stringify({ repo_id, kind }),
        });
        location.reload();
      } catch (e) {
        alert(window.tr("Error: {msg}", {msg: e.message}));
      }
    });
  }

  async function pollDownload(dlId, row) {
    const statusCell = row.querySelector(".dl-status");
    statusCell.innerHTML = '<progress value="0" max="100"></progress> <span class="progress-label">0%</span>';
    const progressEl = statusCell.querySelector("progress");
    const labelEl = statusCell.querySelector(".progress-label");

    while (true) {
      await new Promise(r => setTimeout(r, 2000));
      let dl;
      try {
        dl = await api(`/admin/api/downloads/${dlId}`);
      } catch {
        continue;
      }
      progressEl.value = dl.progress || 0;
      labelEl.textContent = `${Math.round(dl.progress || 0)}%`;

      if (dl.status === "done") { location.reload(); return; }
      if (dl.status === "failed") {
        statusCell.innerHTML = `<span class="pill pill-red">${window.tr("Error")}</span> ${dl.error || ""}`;
        return;
      }
    }
  }

  // ----- Instances -----
  function wireInstanceActions() {
    document.querySelectorAll("#instances-table [data-action]").forEach(btn => {
      const action = btn.dataset.action;
      // Skip main-engine-specific actions — they are wired in
      // wireMainEngineActions() and would otherwise be handled here too.
      if (action === "edit-main" || action === "reload-main" || action === "cancel-edit-main") return;
      btn.addEventListener("click", async () => {
        const id = btn.dataset.id;
        if (action === "delete" && !confirm(window.tr("Really delete this instance?"))) return;
        btn.disabled = true;
        const original = btn.textContent;
        btn.textContent = "…";
        try {
          if (action === "start") await api(`/admin/api/instances/${id}/start`, { method: "POST" });
          else if (action === "stop") await api(`/admin/api/instances/${id}/stop`, { method: "POST" });
          else if (action === "delete") await api(`/admin/api/instances/${id}`, { method: "DELETE" });
          location.reload();
        } catch (e) {
          alert(window.tr("Error: {msg}", {msg: e.message}));
          btn.disabled = false;
          btn.textContent = original;
        }
      });
    });
  }

  // ----- Main engine (Default) -----
  function wireMainEngineActions() {
    const editBtn = document.querySelector('[data-action="edit-main"]');
    const reloadBtn = document.querySelector('[data-action="reload-main"]');
    const dialog = document.getElementById("edit-main-dialog");

    if (reloadBtn) {
      reloadBtn.addEventListener("click", async () => {
        if (!confirm(window.tr("Reload main engine now? Transcriptions on port 8000 will be unavailable during the reload."))) return;
        reloadBtn.disabled = true;
        const orig = reloadBtn.textContent;
        reloadBtn.textContent = "…";
        try {
          await api("/admin/api/main-engine/reload", { method: "POST" });
          pollMainReloadAndReload();
        } catch (e) {
          alert(window.tr("Error: {msg}", {msg: e.message}));
          reloadBtn.disabled = false;
          reloadBtn.textContent = orig;
        }
      });
    }

    if (!editBtn || !dialog) return;

    const form = dialog.querySelector("#edit-main-form");
    const engineSel = form.querySelector('[name="engine"]');
    const modelSel = form.querySelector('[name="model"]');
    const deviceSel = form.querySelector('[name="device"]');
    const computeSel = form.querySelector('[name="compute_type"]');
    const cancelBtn = dialog.querySelector('[data-action="cancel-edit-main"]');

    const allModels = [...modelSel.options].map(o => ({
      value: o.value, label: o.textContent, engine: o.dataset.engine,
    }));

    function refilterModels(currentValue) {
      modelSel.innerHTML = "";
      allModels.filter(o => o.engine === engineSel.value).forEach(o => {
        const opt = document.createElement("option");
        opt.value = o.value; opt.textContent = o.label; opt.dataset.engine = o.engine;
        if (o.value === currentValue) opt.selected = true;
        modelSel.appendChild(opt);
      });
    }

    editBtn.addEventListener("click", () => {
      engineSel.value = editBtn.dataset.engine || "whisperx";
      const currentModel = editBtn.dataset.model || "";
      refilterModels(currentModel);
      deviceSel.value = editBtn.dataset.device || "cpu";
      computeSel.value = editBtn.dataset.computeType || "int8";
      const timeoutInput = document.getElementById("edit-main-timeout");
      const idleInput = document.getElementById("edit-main-idle");
      if (timeoutInput) timeoutInput.value = editBtn.dataset.timeoutSecs || "0";
      if (idleInput) idleInput.value = editBtn.dataset.idleUnloadSecs || "0";
      if (typeof dialog.showModal === "function") dialog.showModal();
      else dialog.setAttribute("open", "");
    });

    engineSel.addEventListener("change", () => refilterModels(""));
    cancelBtn.addEventListener("click", () => dialog.close());

    form.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const payload = {
        engine: engineSel.value,
        model: modelSel.value,
        device: deviceSel.value,
        compute_type: computeSel.value,
        timeout_secs: parseInt(form.timeout_secs.value || "0", 10),
        idle_unload_secs: parseInt(form.idle_unload_secs.value || "0", 10),
      };
      try {
        await api("/admin/api/main-engine", {
          method: "POST",
          body: JSON.stringify(payload),
        });
        dialog.close();
        pollMainReloadAndReload();
      } catch (e) {
        alert(window.tr("Error: {msg}", {msg: e.message}));
      }
    });
  }

  function wireInstanceSettings() {
    const dialog = document.getElementById("instance-settings-dialog");
    const form = document.getElementById("instance-settings-form");
    if (!dialog || !form) return;
    let currentId = null;

    document.querySelectorAll('[data-action="edit-settings"]').forEach((btn) => {
      btn.addEventListener("click", () => {
        currentId = btn.dataset.id;
        document.getElementById("instance-settings-name").textContent = btn.dataset.name || "";
        form.timeout_secs.value = btn.dataset.timeoutSecs || "0";
        form.idle_unload_secs.value = btn.dataset.idleUnloadSecs || "0";
        if (typeof dialog.showModal === "function") dialog.showModal();
        else dialog.setAttribute("open", "");
      });
    });

    form.querySelector('[data-action="cancel-instance-settings"]')
        .addEventListener("click", () => dialog.close());

    form.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      if (!currentId) return;
      try {
        await api(`/admin/api/instances/${currentId}/settings`, {
          method: "POST",
          body: JSON.stringify({
            timeout_secs: parseInt(form.timeout_secs.value || "0", 10),
            idle_unload_secs: parseInt(form.idle_unload_secs.value || "0", 10),
          }),
        });
        dialog.close();
        location.reload();
      } catch (e) {
        alert(window.tr("Error: {msg}", {msg: e.message}));
      }
    });
  }

  // Poll until the main engine finishes reloading, then refresh the page.
  // Reloading can take a long time (large models on CPU). We give up after
  // ~10 minutes and just refresh anyway so the user sees the latest state.
  async function pollMainReloadAndReload() {
    const deadline = Date.now() + 10 * 60 * 1000;
    while (Date.now() < deadline) {
      await new Promise(r => setTimeout(r, 2000));
      try {
        const state = await api("/admin/api/main-engine");
        const status = state.reload && state.reload.status;
        if (status !== "loading") {
          location.reload();
          return;
        }
      } catch {
        // ignore transient errors and keep polling
      }
    }
    location.reload();
  }

  function wireNewInstanceForm() {
    const form = document.getElementById("new-instance-form");
    if (!form) return;

    // Filter model dropdown by chosen engine
    const engineSel = form.querySelector('[name="engine"]');
    const modelSel = form.querySelector('[name="model"]');
    const origOptions = [...modelSel.options].map(o => ({ value: o.value, label: o.textContent, engine: o.dataset.engine }));
    function refilter() {
      modelSel.innerHTML = "";
      origOptions.filter(o => o.engine === engineSel.value).forEach(o => {
        const opt = document.createElement("option");
        opt.value = o.value; opt.textContent = o.label; opt.dataset.engine = o.engine;
        modelSel.appendChild(opt);
      });
    }
    engineSel.addEventListener("change", refilter);
    refilter();

    form.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const payload = {
        name: form.name.value.trim(),
        engine: form.engine.value,
        model: form.model.value,
        device: form.device.value,
        compute_type: form.compute_type.value,
        timeout_secs: parseInt(form.timeout_secs.value || "0", 10),
        idle_unload_secs: parseInt(form.idle_unload_secs.value || "0", 10),
      };
      try {
        await api("/admin/api/instances", {
          method: "POST",
          body: JSON.stringify(payload),
        });
        location.reload();
      } catch (e) {
        alert(window.tr("Error: {msg}", {msg: e.message}));
      }
    });
  }

  return {
    wireKeyActions, wireNewKeyForm,
    wireDownloadButtons, wireCustomDownloadForm,
    wireInstanceActions, wireNewInstanceForm,
    wireMainEngineActions, wireInstanceSettings,
  };
})();
