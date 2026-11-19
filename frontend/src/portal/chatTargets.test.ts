import { describe, expect, it } from "vitest";
import { leadingTarget, mentionsIn, suggestions } from "./chatTargets";

const people = [
  { user_id: "1", name: "Sam Architect" },
  { user_id: "2", name: "Sam" },
  { user_id: "3", name: "Bea Analyst" },
];

describe("chat targets", () => {
  it("switches to one person with @name and back with @everyone", () => {
    expect(leadingTarget("@Sam Architect can you check this?", people)).toEqual({ target: people[0], rest: "can you check this?" });
    expect(leadingTarget("@sam hi", people)).toEqual({ target: people[1], rest: "hi" });
    expect(leadingTarget("@bea", people)).toEqual({ target: people[2], rest: "" }); // unique first name
    expect(leadingTarget("@everyone back to the room", people)).toEqual({ target: "everyone", rest: "back to the room" });
    expect(leadingTarget("no target here", people)).toEqual({ target: null, rest: "no target here" });
    expect(leadingTarget("@nobody hello", people).target).toBeNull();
  });

  it("finds mentions anywhere but not inside email addresses", () => {
    expect(mentionsIn("Thanks @Bea Analyst and @Sam Architect.", people).map((p) => p.user_id)).toEqual(["3", "1"]);
    expect(mentionsIn("mail sam@example.com", people)).toEqual([]);
  });

  it("suggests names while typing after @", () => {
    expect(suggestions("@be", people, true).map((s) => s.label)).toEqual(["@Bea Analyst"]);
    expect(suggestions("hello @ev", people, true)[0]).toEqual({ label: "@everyone", insert: "hello @everyone " });
    expect(suggestions("@ev", people, false)).toEqual([]);
    expect(suggestions("plain text", people, true)).toEqual([]);
  });
});
