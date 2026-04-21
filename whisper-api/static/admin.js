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
        if (!confirm("Diesen Key wirklich widerrufen?")) return;
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
        btn.textContent = "Starte…";
        try {
          const res = await api("/admin/api/downloads", {
            method: "POST",
            body: JSON.stringify({ repo_id, kind }),
          });
          pollDownload(res.id, btn.closest("tr"));
        } catch (e) {
          btn.disabled = false;
          btn.textContent = "Download";
          alert("Download fehlgeschlagen: " + e.message);
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
        alert("Fehler: " + e.message);
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
        statusCell.innerHTML = `<span class="pill pill-red">Fehler</span> ${dl.error || ""}`;
        return;
      }
    }
  }

  // ----- Instances -----
  function wireInstanceActions() {
    document.querySelectorAll("#instances-table [data-action]").forEach(btn => {
      btn.addEventListener("click", async () => {
        const id = btn.dataset.id;
        const action = btn.dataset.action;
        if (action === "delete" && !confirm("Instanz wirklich löschen?")) return;
        btn.disabled = true;
        const original = btn.textContent;
        btn.textContent = "…";
        try {
          if (action === "start") await api(`/admin/api/instances/${id}/start`, { method: "POST" });
          else if (action === "stop") await api(`/admin/api/instances/${id}/stop`, { method: "POST" });
          else if (action === "delete") await api(`/admin/api/instances/${id}`, { method: "DELETE" });
          location.reload();
        } catch (e) {
          alert("Fehler: " + e.message);
          btn.disabled = false;
          btn.textContent = original;
        }
      });
    });
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
        port: form.port.value ? parseInt(form.port.value, 10) : null,
      };
      try {
        await api("/admin/api/instances", {
          method: "POST",
          body: JSON.stringify(payload),
        });
        location.reload();
      } catch (e) {
        alert("Fehler: " + e.message);
      }
    });
  }

  return { wireKeyActions, wireNewKeyForm, wireDownloadButtons, wireCustomDownloadForm, wireInstanceActions, wireNewInstanceForm };
})();
