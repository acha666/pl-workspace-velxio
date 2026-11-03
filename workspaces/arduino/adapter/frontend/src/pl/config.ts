/** Build-time switch; ordinary Velxio builds retain their existing behavior. */
export const PL_MODE = import.meta.env.VITE_PL_WORKSPACE === 'true';

declare global {
  interface Window {
    __VELXIO_WORKSPACE_BASE__?: string;
  }
}

export function workspaceBase(): string {
  const base = window.__VELXIO_WORKSPACE_BASE__;
  if (!base || !base.startsWith('/') || base.startsWith('//')) {
    throw new Error('The PrairieLearn workspace base URL is missing or invalid.');
  }
  return base.replace(/\/+$/, '') + '/';
}

export function assetUrl(path: string): string {
  if (!PL_MODE) return path;
  return new URL(workspaceBase() + path.replace(/^\/+/, ''), window.location.origin).href;
}

const unavailableCommands = new Set([
  'project.new',
  'project.open',
  'project.import',
  'file.new',
  'project.share',
  'project.githubSync',
  'project.connectAgent',
  'project.exportBom',
  'project.exportScreenshot',
  'firmware.upload',
  'sim.record',
  'account.myProjects',
  'account.login',
  'help.whatsNew',
]);

export function workspaceCommandAllowed(id: string): boolean {
  return !PL_MODE || !unavailableCommands.has(id);
}

/** The Help menu offers only the AGPL source of this build. */
export function workspaceHelpItems() {
  return [
    { kind: 'link' as const, href: assetUrl('pl-adapter-source.tar.gz'), label: 'Source & licenses' },
  ];
}
