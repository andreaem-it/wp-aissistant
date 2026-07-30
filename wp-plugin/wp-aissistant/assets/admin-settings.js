(function ($) {
  const stage = document.getElementById("wpai-preview-stage");
  const preview = document.getElementById("wpai-preview-window");
  if (!stage || !preview) return;

  const title = preview.querySelector("strong");
  const subtitle = preview.querySelector("small");
  const welcome = preview.querySelector(".wpai-preview-body span");
  const launcher = stage.querySelector(".wpai-preview-launcher span");
  const colorOutput = document.getElementById("wpai-color-value");

  document.querySelectorAll("[data-preview]").forEach((field) => {
    field.addEventListener("input", function () {
      const value = this.value;
      if (this.dataset.preview === "title") title.textContent = value || "AI Assistant";
      if (this.dataset.preview === "subtitle") subtitle.textContent = value || "Di solito risponde subito";
      if (this.dataset.preview === "welcome") welcome.textContent = value || "Ciao! Come posso aiutarti oggi?";
      if (this.dataset.preview === "launcher") launcher.textContent = value;
      if (this.dataset.preview === "color") {
        stage.style.setProperty("--wpai-preview-color", value);
        colorOutput.textContent = value;
      }
      if (this.dataset.preview === "position") stage.dataset.position = value;
      if (this.dataset.preview === "theme") preview.dataset.theme = value;
    });
  });

  const color = document.getElementById("widget_color");
  const position = document.getElementById("widget_position");
  const theme = document.getElementById("widget_theme");
  stage.style.setProperty("--wpai-preview-color", color.value);
  stage.dataset.position = position.value;
  preview.dataset.theme = theme.value;

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
