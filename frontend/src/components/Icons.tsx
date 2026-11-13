// Font Awesome 4.7 icons (same icon set as duebendorf.ch; OFL/MIT, bundled locally).
type P = { size?: number; className?: string };

const fa = (name: string) => ({ size, className }: P) => (
  <i className={`fa fa-${name} ${className ?? ""}`} style={size ? { fontSize: Math.round(size * 0.95) } : undefined} aria-hidden="true" />
);

export const Search = fa("search");
export const Chat = fa("comments-o");
export const Folder = fa("folder-open-o");
export const Calendar = fa("calendar");
export const Plus = fa("plus");
export const Play = fa("play-circle-o");
export const Doc = fa("file-pdf-o");
export const Video = fa("video-camera");
export const Sparkle = fa("magic");
export const Close = fa("times");
export const External = fa("external-link");
export const Trash = fa("trash-o");
export const Download = fa("download");
export const Note = fa("sticky-note-o");
export const Logout = fa("sign-out");
export const Agenda = fa("list-ol");
export const Insert = fa("share");
export const Bars = fa("bars");
export const AngleRight = fa("angle-right");
export const AngleDown = fa("angle-down");
export const User = fa("user-o");
export const Help = fa("question-circle-o");
export const Info = fa("info-circle");
export const Print = fa("print");
export const Home = fa("home");

/** Text wordmark (deliberately not the city's coat of arms / logo). */
export const Wordmark = () => (
  <span className="wordmark">
    <span className="wordmark-main">Ratsarchiv</span>
    <span className="wordmark-sub">DemocrAI · Gemeinderat Dübendorf</span>
  </span>
);
export const Globe = fa("globe");
export const Language = fa("language");
