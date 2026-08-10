// @vitest-environment jsdom
import { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { SectionTabs, TabPanel } from "./PageLayout.jsx";

function Example() {
  const [active, setActive] = useState("first");
  const items = [
    { key: "first", label: "Prima" },
    { key: "second", label: "Seconda" },
  ];
  return (
    <>
      <SectionTabs items={items} active={active} onChange={setActive} />
      <TabPanel active={active} name="first">Contenuto uno</TabPanel>
      <TabPanel active={active} name="second">Contenuto due</TabPanel>
    </>
  );
}

describe("SectionTabs", () => {
  it("mostra una sola sezione e aggiorna lo stato accessibile", () => {
    render(<Example />);

    expect(screen.getByRole("tab", { name: "Prima" }).getAttribute("aria-selected")).toBe("true");
    expect(screen.queryByText("Contenuto due")).toBeNull();

    fireEvent.click(screen.getByRole("tab", { name: "Seconda" }));

    expect(screen.getByRole("tab", { name: "Seconda" }).getAttribute("aria-selected")).toBe("true");
    expect(screen.queryByText("Contenuto uno")).toBeNull();
    expect(screen.getByText("Contenuto due")).toBeTruthy();
  });
});
