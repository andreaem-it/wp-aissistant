(function ($) {
  const stage = document.getElementById("wpai-preview-stage");
  const preview = document.getElementById("wpai-preview-window");
  if (!stage || !preview) return;

  const title = preview.querySelector("strong");
  const subtitle = preview.querySelector("small");
  const welcome = preview.querySelector(".wpai-preview-body span");
  const disclosure = preview.querySelector(".wpai-preview-disclosure-copy");
  const launcher = stage.querySelector(".wpai-preview-launcher span");
  const launcherIcon = stage.querySelector(".wpai-preview-launcher i");
  const previewAvatar = preview.querySelector(".wpai-preview-header img");
  const previewStatus = preview.querySelector(".wpai-preview-header small");
  const previewInput = preview.querySelector(".wpai-preview-input span");
  const colorOutput = document.getElementById("wpai-color-value");

  const tabs = Array.from(document.querySelectorAll("[data-settings-tab]"));
  const panels = Array.from(document.querySelectorAll("[data-settings-panel]"));
  function activateTab(name) {
    tabs.forEach((tab) => tab.setAttribute("aria-selected", String(tab.dataset.settingsTab === name)));
    panels.forEach((panel) => { panel.hidden = panel.dataset.settingsPanel !== name; });
    sessionStorage.setItem("wpai_settings_tab", name);
  }
  tabs.forEach((tab) => tab.addEventListener("click", () => activateTab(tab.dataset.settingsTab)));
  activateTab(sessionStorage.getItem("wpai_settings_tab") || "general");

  document.querySelectorAll("[data-preview]").forEach((field) => {
    field.addEventListener("input", function () {
      const value = this.value;
      if (this.dataset.preview === "title") title.textContent = value || "AI Assistant";
      if (this.dataset.preview === "subtitle") subtitle.textContent = value || "Di solito risponde subito";
      if (this.dataset.preview === "welcome") welcome.textContent = value || "Ciao! Come posso aiutarti oggi?";
      if (this.dataset.preview === "disclosure") disclosure.textContent = value || "Stai parlando con un assistente virtuale basato su intelligenza artificiale.";
      if (this.dataset.preview === "launcher") launcher.textContent = value;
      if (this.dataset.preview === "color") {
        stage.style.setProperty("--wpai-preview-color", value);
        colorOutput.textContent = value;
      }
      if (this.dataset.preview === "position") stage.dataset.position = value;
      if (this.dataset.preview === "theme") preview.dataset.theme = value;
      if (this.dataset.preview === "launcher-style") stage.dataset.launcherStyle = value;
      if (this.dataset.preview === "window-style") preview.dataset.windowStyle = value;
    });
  });

  const color = document.getElementById("widget_color");
  const position = document.getElementById("widget_position");
  const theme = document.getElementById("widget_theme");
  const supportEnabled = document.getElementById("support_hours_enabled");
  const supportSchedule = document.getElementById("wpai-support-schedule");
  stage.style.setProperty("--wpai-preview-color", color.value);
  stage.dataset.position = position.value;
  preview.dataset.theme = theme.value;
  stage.dataset.launcherStyle = document.getElementById("widget_launcher_style").value;
  preview.dataset.windowStyle = document.getElementById("widget_window_style").value;

  function previewSetting(id, target, key) {
    const field = document.getElementById(id);
    if (!field) return;
    const apply = () => { target.dataset[key] = field.value; };
    field.addEventListener("input", apply); apply();
  }
  previewSetting("widget_window_size", preview, "windowSize");
  previewSetting("widget_launcher_size", stage, "launcherSize");
  previewSetting("widget_header_style", preview, "headerStyle");
  previewSetting("widget_corner_style", preview, "cornerStyle");
  previewSetting("widget_font_size", preview, "fontSize");
  const iconField = document.getElementById("widget_launcher_icon");
  if (iconField) { const applyIcon = () => { launcherIcon.className = `fa-solid fa-${iconField.value}`; }; iconField.addEventListener("input", applyIcon); applyIcon(); }
  const placeholderField = document.getElementById("widget_input_placeholder");
  if (placeholderField) { const applyPlaceholder = () => { previewInput.textContent = placeholderField.value || "Scrivi un messaggio…"; }; placeholderField.addEventListener("input", applyPlaceholder); applyPlaceholder(); }
  const avatarField = document.getElementById("widget_show_avatar");
  const statusField = document.getElementById("widget_show_status");
  if (avatarField) { const applyAvatar = () => { previewAvatar.hidden = !avatarField.checked; }; avatarField.addEventListener("change", applyAvatar); applyAvatar(); }
  if (statusField) { const applyStatus = () => { previewStatus.hidden = !statusField.checked; }; statusField.addEventListener("change", applyStatus); applyStatus(); }

  function updateSupportSchedule() {
    if (!supportEnabled || !supportSchedule) return;
    supportSchedule.classList.toggle("is-disabled", !supportEnabled.checked);
  }
  if (supportEnabled) supportEnabled.addEventListener("change", updateSupportSchedule);
  updateSupportSchedule();

  const debug = document.getElementById("wpai-debug-data");
  document.getElementById("wpai-copy-debug")?.addEventListener("click", async function () {
    await navigator.clipboard.writeText(debug.value);
    this.textContent = "Copiato";
  });
  document.getElementById("wpai-download-debug")?.addEventListener("click", function () {
    const url = URL.createObjectURL(new Blob([debug.value], { type: "application/json" }));
    const link = document.createElement("a");
    link.href = url; link.download = "wp-aissistant-debug.json"; link.click();
    URL.revokeObjectURL(url);
  });

  let frame;
  $("#wpai-image-select").on("click", function (event) {
    event.preventDefault();
    if (frame) { frame.open(); return; }
    frame = wp.media({ title: "Scegli immagine widget", multiple: false });
    frame.on("select", function () {
      const attachment = frame.state().get("selection").first().toJSON();
      $("#widget_image").val(attachment.url);
      $("#wpai-image-preview, .wpai-preview-header img").attr("src", attachment.url);
      $("#wpai-image-clear").prop("hidden", false);
    });
    frame.open();
  });

  $("#wpai-image-clear").on("click", function (event) {
    event.preventDefault();
    $("#widget_image").val("");
    $("#wpai-image-preview, .wpai-preview-header img").attr("src", WPAI_ADMIN.defaultImage);
    $(this).prop("hidden", true);
  });
})(jQuery);
