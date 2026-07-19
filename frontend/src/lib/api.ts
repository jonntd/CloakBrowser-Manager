/**
 * API client for CloakAccounts desktop app.
 * Uses Tauri invoke in the desktop shell; falls back to a clear error if not available.
 */

import { invoke } from "@tauri-apps/api/core";

export interface Tag {
  tag: string;
  color: string | null;
}

export interface Account {
  id: string;
  name: string;
  site: string | null;
  notes: string | null;
  tags: Tag[];
  user_data_dir: string;
  fingerprint_seed: number;
  proxy: string | null;
  timezone: string | null;
  locale: string | null;
  platform: string;
  user_agent: string | null;
  screen_width: number;
  screen_height: number;
  gpu_vendor: string | null;
  gpu_renderer: string | null;
  hardware_concurrency: number | null;
  humanize: boolean;
  human_preset: string;
  geoip: boolean;
  color_scheme: string | null;
  launch_args: string[];
  created_at: string;
  updated_at: string;
  status: "running" | "stopped";
}

/** Shape sent when creating / updating an account. */
export interface AccountCreateData {
  name: string;
  site?: string | null;
  notes?: string | null;
  tags?: Tag[];
  fingerprint_seed?: number | null;
  proxy?: string | null;
  timezone?: string | null;
  locale?: string | null;
  platform?: string;
  user_agent?: string | null;
  screen_width?: number;
  screen_height?: number;
  gpu_vendor?: string | null;
  gpu_renderer?: string | null;
  hardware_concurrency?: number | null;
  humanize?: boolean;
  human_preset?: string;
  geoip?: boolean;
  color_scheme?: string | null;
  launch_args?: string[];
}

export interface OpenResult {
  account_id: string;
  status: string;
  pid: number;
}

// Back-compat aliases used by reused form components
export type Profile = Account;
export type ProfileCreateData = AccountCreateData;

class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function call<T>(cmd: string, args?: Record<string, unknown>): Promise<T> {
  try {
    return await invoke<T>(cmd, args);
  } catch (err) {
    const msg = typeof err === "string" ? err : err instanceof Error ? err.message : String(err);
    throw new ApiError(500, msg);
  }
}

export const api = {
  listAccounts: () => call<Account[]>("list_accounts"),

  getAccount: (id: string) => call<Account>("get_account", { id }),

  createAccount: (data: AccountCreateData) =>
    call<Account>("create_account", { payload: data }),

  updateAccount: (id: string, data: Partial<AccountCreateData>) =>
    call<Account>("update_account", { id, payload: data }),

  removeAccount: (id: string) => call<void>("remove_account", { id }),

  openAccount: (id: string, url?: string | null) =>
    call<OpenResult>("open_account", { id, url: url ?? null }),

  stopAccount: (id: string) => call<void>("stop_account", { id }),

  accountStatus: (id: string) => call<string>("account_status", { id }),

  // Aliases matching old profile API so existing hooks/components compile with minimal churn
  listProfiles: () => call<Account[]>("list_accounts"),
  getProfile: (id: string) => call<Account>("get_account", { id }),
  createProfile: (data: AccountCreateData) =>
    call<Account>("create_account", { payload: data }),
  updateProfile: (id: string, data: Partial<AccountCreateData>) =>
    call<Account>("update_account", { id, payload: data }),
  deleteProfile: (id: string) => call<void>("remove_account", { id }),
  launchProfile: (id: string) => call<OpenResult>("open_account", { id, url: null }),
  stopProfile: (id: string) => call<void>("stop_account", { id }),
};

export { ApiError };
