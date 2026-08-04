// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";

import { AttachmentPreview } from "./Conversations.jsx";
import { api } from "./api.js";

const ATTACHMENT = { id: 7, filename: "foto.jpg", content_type: "image/jpeg", size_bytes: 2048 };

describe("anteprima allegato", () => {
  let created;
  let revoked;

  beforeEach(() => {
    created = [];
    revoked = [];
    URL.createObjectURL = vi.fn(() => {
      const url = `blob:mock/${created.length}`;
      created.push(url);
      return url;
    });
    URL.revokeObjectURL = vi.fn((url) => revoked.push(url));
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("mostra l'immagine da un object URL e lo revoca allo smontaggio", async () => {
    const blob = new Blob([new Uint8Array([137, 80, 78, 71])], { type: "image/png" });
    vi.spyOn(api, "downloadAttachment").mockResolvedValue(blob);

    const { unmount } = render(<AttachmentPreview attachment={ATTACHMENT} onOpen={() => {}} />);

    const image = await screen.findByAltText("foto.jpg");
    expect(image.getAttribute("src")).toBe(created[0]);
    // i byte arrivano dalla sessione operatore, non da una URL indovinabile
    expect(api.downloadAttachment).toHaveBeenCalledWith(7);

    unmount();
    expect(revoked).toEqual(created);
  });

  it("non lascia un riquadro rotto se il download non riesce", async () => {
    vi.spyOn(api, "downloadAttachment").mockRejectedValue(new Error("403"));

    const { container } = render(<AttachmentPreview attachment={ATTACHMENT} onOpen={() => {}} />);

    await waitFor(() => expect(container.firstChild).toBeNull());
    expect(created).toEqual([]);
  });
});
