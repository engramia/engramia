const READER = [
  "health", "metrics", "recall", "feedback:read", "skills:search",
  "jobs:list", "jobs:read", "analytics:read",
];

const EDITOR = [
  ...READER,
  "learn", "evaluate", "compose", "evolve", "analyze_failures",
  "skills:register", "aging", "feedback:decay", "jobs:cancel", "analytics:rollup",
];

const ADMIN = [
  ...EDITOR,
  "patterns:delete", "import", "export",
  "keys:create", "keys:list", "keys:revoke", "keys:rotate",
  "governance:read", "governance:write", "governance:admin", "governance:delete",
];

const ROLE_PERMISSIONS: Record<string, Set<string>> = {
  reader: new Set(READER),
  editor: new Set(EDITOR),
  admin: new Set(ADMIN),
  owner: new Set(["*"]),
};

export function hasPermission(role: string, perm: string): boolean {
  const perms = ROLE_PERMISSIONS[role];
  if (!perms) return false;
  return perms.has("*") || perms.has(perm);
}
