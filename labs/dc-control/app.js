(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const durationOptions = [[15, "15 分钟"], [30, "30 分钟"], [60, "1 小时"], [120, "2 小时"], [240, "4 小时"]];
  const apiBase = "/dc/api";
  const storageKey = "mira.cloud-auth.session.v1";
  let current = null, draft = null, busy = false, lastRead = 0;

  function token() {
    try {
      const stored = JSON.parse(sessionStorage.getItem(storageKey) || "null");
      return typeof stored?.sessionToken === "string" ? stored.sessionToken : null;
    } catch { return null; }
  }
  function message(text, kind = "") {
    const el = $("message");
    el.hidden = !text;
    el.textContent = text || "";
    el.className = "message " + kind;
  }
  function authWarning(show) {
    $("auth-warning").hidden = !show;
  }
  async function api(path, method = "GET", data) {
    const bearer = token();
    if (!bearer) throw new Error("请先登录 Mira Cloud Account");
    const response = await fetch(apiBase + path, {
      method,
      cache: "no-store",
      credentials: "same-origin",
      headers: {
        Authorization: "Bearer " + bearer,
        ...(method !== "GET" ? { "Content-Type": "application/json" } : {})
      },
      body: method !== "GET" ? JSON.stringify(data || {}) : undefined
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
      if (response.status === 401) authWarning(true);
      throw new Error(body.error || "操作失败（HTTP " + response.status + "）");
    }
    return body;
  }
  function timeString(seconds) {
    if (!Number.isFinite(seconds)) return "—";
    const s = Math.max(0, Math.floor(seconds));
    return Math.floor(s / 3600) > 0
      ? Math.floor(s / 3600) + "小时 " + Math.floor((s % 3600) / 60) + "分"
      : Math.floor(s / 60) + "分 " + String(s % 60).padStart(2, "0") + "秒";
  }
  function isRunning() {
    return Boolean(current && (current.running || current.legacyRunning));
  }
  function renderDuration() {
    $("durations").replaceChildren(...durationOptions.map(([value, label]) => {
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = label;
      b.className = draft?.durationMinutes === value ? "selected" : "";
      b.setAttribute("aria-pressed", draft?.durationMinutes === value ? "true" : "false");
      b.addEventListener("click", () => {
        draft.durationMinutes = value;
        renderDuration();
        updateActions();
      });
      return b;
    }));
  }
  function loadPolicy(data) {
    draft = { ...data };
    $("memory-select").value = String(draft.memoryMiB);
    $("cpu-select").value = String(draft.cpuPercent);
    $("headroom-select").value = String(draft.minAvailableMiB);
    renderDuration();
  }
  function isDirty() {
    return draft && current && Object.keys(draft).some(k => draft[k] !== current.policy[k]);
  }
  function updateActions() {
    $("start").disabled = busy || !current || isRunning();
    $("stop").disabled = busy || !current || !isRunning();
    $("save").disabled = busy || !current || !isDirty();
    $("refresh").disabled = busy;
    $("start").textContent = busy ? "正在处理…" : "启动 DC";
    $("stop").textContent = "停止服务";
  }
  function render() {
    if (!current) return;
    const running = isRunning();
    const legacy = current.legacyRunning && !current.running;
    $("header-dot").classList.toggle("on", running);
    $("header-state").textContent = running ? "在线 · 服务运行中" : "离线 · 已停止";
    $("status-symbol").className = "status-symbol " + (running ? "running" : "stopped");
    $("status-text").textContent = running ? "运行中" : "已停止";
    $("state-explain").textContent = running ? (legacy ? "来自此前的临时试运行服务" : "DC 设备进程已启动") : "需要时再启动，减少服务器资源占用";
    if (running && current.remainingSeconds !== null) {
      const elapsed = Math.floor((Date.now() - lastRead) / 1000);
      $("remaining").textContent = timeString(current.remainingSeconds - elapsed);
    } else {
      $("remaining").textContent = legacy ? "临时服务" : "—";
    }
    $("memory").textContent = current.memoryBytes === null ? "—" : Math.round(current.memoryBytes / 1024 / 1024) + " MiB";
    $("last-updated").textContent = "最后更新 " + new Date(current.at).toLocaleTimeString("zh-CN", {hour: "2-digit", minute: "2-digit", second: "2-digit"});
    updateActions();
  }
  async function refresh(quiet = false) {
    if (busy) return;
    if (!token()) {
      authWarning(true);
      $("header-state").textContent = "请先登录";
      return;
    }
    try {
      const previous = current?.policy;
      current = await api("/status");
      lastRead = Date.now();
      if (!draft || !previous || !Object.keys(draft).some(k => draft[k] !== previous[k])) {
        loadPolicy(current.policy);
      }
      authWarning(false);
      if (!quiet) message("");
      render();
    } catch (error) {
      current = null;
      updateActions();
      if (!quiet) message(error.message, "error");
      $("header-state").textContent = "无法连接";
    }
  }
  async function savePolicy() {
    if (!draft) return false;
    current = await api("/policy", "PUT", draft);
    lastRead = Date.now();
    loadPolicy(current.policy);
    render();
    return true;
  }
  async function mutate(kind) {
    if (busy) return;
    busy = true;
    updateActions();
    message("");
    try {
      if (kind === "save") {
        await savePolicy();
        message("策略已保存，下次启动时生效。", "success");
      }
      if (kind === "start") {
        if (isDirty()) await savePolicy();
        current = await api("/start", "POST");
        lastRead = Date.now();
        message("已发送启动命令，DC 正在建立远程连接。", "success");
      }
      if (kind === "stop") {
        current = await api("/stop", "POST");
        lastRead = Date.now();
        message("DC 服务已停止，其他容器未受影响。", "success");
      }
    } catch (error) {
      message(error.message, "error");
    } finally {
      busy = false;
      updateActions();
      await refresh(true);
    }
  }
  for (const [key, elementId] of [["memoryMiB", "memory-select"], ["cpuPercent", "cpu-select"], ["minAvailableMiB", "headroom-select"]]) {
    $(elementId).addEventListener("change", () => {
      if (!draft) return;
      draft[key] = Number($(elementId).value);
      updateActions();
    });
  }
  $("start").addEventListener("click", () => void mutate("start"));
  $("save").addEventListener("click", () => void mutate("save"));
  $("refresh").addEventListener("click", () => void refresh());
  $("stop").addEventListener("click", () => $("confirm-dialog").showModal());
  $("confirm-dialog").addEventListener("close", () => {
    if ($("confirm-dialog").returnValue === "confirm") void mutate("stop");
  });
  const defaultPolicy = {durationMinutes: 30, memoryMiB: 384, cpuPercent: 50, minAvailableMiB: 512};
  loadPolicy(defaultPolicy);
  updateActions();
  void refresh();
  setInterval(() => { if (current?.remainingSeconds != null) render(); }, 1000);
  setInterval(() => { if (!document.hidden) void refresh(true); }, 10000);
})();