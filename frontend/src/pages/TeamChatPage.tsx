import { useEffect, useMemo, useState } from "react";
import { ApiError, api } from "../api";
import { Skeleton } from "../components/ui";
import { TeamChat, globalChat } from "../portal/Collaboration";

const INTRO: Record<string, [string, string]> = {
  manager: ["Team chat", "The professional team across every project. Type @name to talk to one person privately."],
  professional: ["Team chat", "The professional team across every project. Type @name to talk to one person privately. Project owners do not see this chat."],
  admin: ["Messages", "Administrators are not part of the team chat. Message project owners and project managers directly with @name."],
  owner: ["Messages", "Message a project manager or an administrator directly. Start with @name."],
};

/** Team chat for professionals and project managers; direct messages for everyone. Not tied to any project. */
export function TeamChatPage() {
  const [channels, setChannels] = useState<{ key: string; name: string }[] | null>(null);
  const [kind, setKind] = useState("professional");
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    api.globalChannels().then((r) => { setKind(r.kind); setChannels(r.items); })
      .catch((e: unknown) => setError(e instanceof ApiError ? e.message : "Could not load your messages."));
    const timer = window.setInterval(() => { if (!document.hidden) setTick((n) => n + 1); }, 5000);
    return () => window.clearInterval(timer);
  }, []);
  const source = useMemo(() => (channels ? globalChat(channels) : null), [channels]);
  const [title, intro] = INTRO[kind] ?? INTRO.professional;
  return (
    <section className="card stack">
      <div>
        <p className="eyebrow">Team</p>
        <h1>{channels ? title : "Messages"}</h1>
        {channels && <p className="muted">{intro}</p>}
      </div>
      {error && <p role="alert" className="error">{error}</p>}
      {!error && !source && <Skeleton title={false} />}
      {source && <TeamChat source={source} tick={tick} label={channels?.length ? "Message the team" : "Message someone directly"} />}
    </section>
  );
}
