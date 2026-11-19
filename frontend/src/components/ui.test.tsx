import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { IdentityTag, StatusPill } from "./ui";

describe("design system markers", () => {
  it("gives workflow statuses conventional status colours, not brand colours", () => {
    render(
      <>
        <StatusPill label="Approved" />
        <StatusPill label="Blocked" />
        <StatusPill label="Awaiting Review" />
        <StatusPill label="In Progress" />
        <StatusPill label="Something new" />
      </>,
    );
    expect(screen.getByText("Approved")).toHaveClass("pill", "pill-success");
    expect(screen.getByText("Blocked")).toHaveClass("pill-blocked");
    expect(screen.getByText("Awaiting Review")).toHaveClass("pill-pending");
    expect(screen.getByText("In Progress")).toHaveClass("pill-progress");
    expect(screen.getByText("Something new")).toHaveClass("pill-neutral");
  });

  it("marks AI, people and the system differently and says which in text", () => {
    const { container } = render(
      <>
        <IdentityTag kind="ai">Business Analyst team</IdentityTag>
        <IdentityTag kind="human">Asha</IdentityTag>
        <IdentityTag kind="system" />
      </>,
    );
    expect(container.querySelector(".identity-ai")).toHaveTextContent("AIBusiness Analyst team");
    expect(container.querySelector(".identity-human")).toHaveTextContent("PersonAsha");
    expect(container.querySelector(".identity-system")).toHaveTextContent("System");
  });
});
