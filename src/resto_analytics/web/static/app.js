// Страница загрузки: отправляет файл в API и рисует ответ. Без фреймворков.
(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const fileInput = $("file");
  const drop = $("drop");
  const errorBox = $("error");
  const selects = ["margin_base", "service_source", "last_column"].map($);
  let currentFile = null;

  const money = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 });
  const coef = new Intl.NumberFormat("ru-RU", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const pct = new Intl.NumberFormat("ru-RU", { minimumFractionDigits: 1, maximumFractionDigits: 1 });

  function el(tag, attrs = {}, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs)) {
      if (key === "class") node.className = value;
      else node.setAttribute(key, value);
    }
    for (const child of children) {
      if (child == null) continue;
      node.append(child instanceof Node ? child : document.createTextNode(String(child)));
    }
    return node;
  }

  function formData(extra = {}) {
    const fd = new FormData();
    fd.append("file", currentFile);
    for (const s of selects) fd.append(s.name, s.value);
    for (const [k, v] of Object.entries(extra)) fd.append(k, v);
    return fd;
  }

  async function errorText(resp) {
    try {
      const body = await resp.json();
      if (typeof body.detail === "string") return body.detail;
    } catch (_) { /* не JSON */ }
    return `Ошибка сервера (${resp.status}). Попробуйте ещё раз.`;
  }

  function showError(message) {
    errorBox.textContent = message;
    errorBox.hidden = !message;
  }

  async function run() {
    if (!currentFile) return;
    showError("");
    drop.classList.add("is-loading");
    try {
      const resp = await fetch("/api/v1/sales-summary", { method: "POST", body: formData() });
      if (!resp.ok) {
        $("result").hidden = true;
        showError(await errorText(resp));
        return;
      }
      render(await resp.json());
    } catch (_) {
      showError("Нет связи с сервером. Проверьте интернет и попробуйте ещё раз.");
    } finally {
      drop.classList.remove("is-loading");
    }
  }

  function render(data) {
    $("r-title").textContent = data.meta.title;
    const bits = [];
    if (data.meta.warehouses.length) bits.push(`Складов: ${data.meta.warehouses.length}`);
    bits.push(`Позиций: ${data.line_count}`);
    if (data.excluded_lines) bits.push(`не учтено по настройкам: ${data.excluded_lines}`);
    $("r-meta").textContent = bits.join(" · ");

    const recon = $("recon");
    if (data.reconciliation) {
      const r = data.reconciliation;
      recon.hidden = false;
      recon.className = "pill " + (r.ok ? "ok" : "bad");
      recon.textContent = r.ok
        ? `✓ Сходится с итогом файла: ${money.format(r.file_revenue)} тг`
        : `Не сходится с итогом файла: строки ${money.format(r.lines_revenue)} тг, итог ${money.format(r.file_revenue)} тг`;
    } else {
      recon.hidden = true;
    }

    const t = data.total;
    $("kpis").replaceChildren(
      kpi("Продажи без обслуживания", money.format(t.sales_net), "тг"),
      kpi("Обслуживание 10%", money.format(t.service), "тг"),
      kpi("Себестоимость", money.format(t.cost), "тг"),
      kpi("Валовый доход", money.format(t.gross), "тг"),
      kpi("Средний коэффициент", t.coefficient == null ? "—" : coef.format(t.coefficient), ""),
    );

    $("base-note").textContent = `Доход, коэффициент и доля считаются от ${data.margin_base_label}.`;
    $("th-last").textContent = data.last_column_title;
    const isShare = data.settings.last_column === "share";

    const tbody = $("tbody");
    tbody.replaceChildren();
    data.groups.forEach((g, index) => {
      const id = `items-${index}`;
      const toggle = el("button", { type: "button", "aria-expanded": "false", "aria-controls": id }, g.name);
      const nameCell = el("td", {}, el("div", { class: "gname" }, toggle,
        g.sources.length > 1 || (g.sources[0] && g.sources[0] !== g.name)
          ? el("span", { class: "src" }, g.sources.join(", ")) : null));
      const row = el("tr", { class: "group" }, nameCell, ...figureCells(g, isShare));
      const itemRows = g.items.map((it) => el("tr", { class: "item", "data-group": id, hidden: "" },
        el("td", {}, it.name),
        el("td", {}, money.format(it.sales_net)),
        el("td", {}, money.format(it.service)),
        el("td", {}, money.format(it.sales_total)),
        el("td", {}, money.format(it.cost)),
        el("td", {}, money.format(it.gross)),
        el("td", {}, it.coefficient == null ? el("span", { class: "nocost" }, "нет себест.") : coef.format(it.coefficient)),
        el("td", {}, `${money.format(it.quantity)} шт`),
      ));
      row.addEventListener("click", () => {
        const open = toggle.getAttribute("aria-expanded") !== "true";
        toggle.setAttribute("aria-expanded", String(open));
        for (const r of itemRows) r.hidden = !open;
      });
      tbody.append(row, ...itemRows);
    });

    $("tfoot").replaceChildren(el("tr", {}, el("td", {}, "Итого"), ...figureCells(t, isShare, true)));
    renderIssues(data.issues);
    $("result").hidden = false;
    $("explain").hidden = true;
  }

  function figureCells(g, isShare, isTotal = false) {
    const last = g.last_value == null ? "—" : pct.format(g.last_value);
    const lastCell = isShare && !isTotal
      ? el("span", { class: "share" }, el("span", { class: "bar", "aria-hidden": "true" },
          el("span", { style: `width:${Math.min(100, g.share)}%` })), last)
      : last;
    return [
      el("td", {}, money.format(g.sales_net)),
      el("td", {}, money.format(g.service)),
      el("td", {}, money.format(g.sales_total)),
      el("td", {}, money.format(g.cost)),
      el("td", {}, money.format(g.gross)),
      el("td", {}, g.coefficient == null ? el("span", { class: "nocost" }, "нет себестоимости") : coef.format(g.coefficient)),
      el("td", {}, lastCell),
    ];
  }

  function kpi(label, value, unit) {
    return el("div", { class: "kpi" },
      el("div", { class: "kpi-label" }, label),
      el("div", { class: "kpi-value" }, value, unit ? el("small", {}, ` ${unit}`) : null));
  }

  function renderIssues(issues) {
    const box = $("issues");
    const cards = $("issue-cards");
    cards.replaceChildren();
    const byKind = new Map();
    for (const issue of issues) {
      if (!byKind.has(issue.kind)) byKind.set(issue.kind, []);
      byKind.get(issue.kind).push(issue);
    }
    for (const list of byKind.values()) {
      const first = list[0];
      const shown = list.slice(0, 6);
      const ul = el("ul", {}, ...shown.map((i) => el("li", {},
        el("span", {}, i.item),
        el("span", {}, first.kind === "zero_cost"
          ? `${money.format(i.sales)} тг`
          : `${coef.format(i.coefficient)} · ${money.format(i.sales)} тг`))));
      if (list.length > shown.length) ul.append(el("li", {}, el("span", { class: "muted" }, `и ещё ${list.length - shown.length} — в Excel на листе «Проверка данных»`)));
      cards.append(el("article", { class: `issue ${first.severity}` },
        el("h3", {}, first.title, el("span", { class: "count" }, list.length)),
        el("p", {}, first.hint), ul));
    }
    box.hidden = issues.length === 0;
  }

  function filenameFrom(resp) {
    const header = resp.headers.get("Content-Disposition") || "";
    const star = header.match(/filename\*=UTF-8''([^;]+)/i);
    if (star) return decodeURIComponent(star[1]);
    return "svodka.xlsx";
  }

  async function download() {
    if (!currentFile) return;
    const btn = $("download");
    btn.disabled = true;
    showError("");
    try {
      const resp = await fetch("/api/v1/sales-summary/xlsx", {
        method: "POST",
        body: formData({ formulas: $("formulas").checked ? "true" : "false" }),
      });
      if (!resp.ok) { showError(await errorText(resp)); return; }
      const url = URL.createObjectURL(await resp.blob());
      const a = el("a", { href: url, download: filenameFrom(resp) });
      document.body.append(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 10_000);
    } catch (_) {
      showError("Не удалось скачать файл. Проверьте интернет и попробуйте ещё раз.");
    } finally {
      btn.disabled = false;
    }
  }

  function useFile(file) {
    if (!file) return;
    currentFile = file;
    $("drop-title").textContent = file.name;
    $("drop-sub").textContent = "Нажмите, чтобы выбрать другой файл";
    run();
  }

  fileInput.addEventListener("change", () => useFile(fileInput.files[0]));
  for (const s of selects) s.addEventListener("change", run);
  $("download").addEventListener("click", download);
  ["dragenter", "dragover"].forEach((type) => drop.addEventListener(type, (e) => {
    e.preventDefault();
    drop.classList.add("is-over");
  }));
  ["dragleave", "drop"].forEach((type) => drop.addEventListener(type, (e) => {
    e.preventDefault();
    drop.classList.remove("is-over");
  }));
  drop.addEventListener("drop", (e) => useFile(e.dataTransfer.files[0]));
})();
