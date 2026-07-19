import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import { useAccounts } from "./useAccounts";

vi.mock("../lib/api", () => ({
  api: {
    listAccounts: vi.fn(),
    createAccount: vi.fn(),
    updateAccount: vi.fn(),
    removeAccount: vi.fn(),
    openAccount: vi.fn(),
    stopAccount: vi.fn(),
  },
}));

import { api } from "../lib/api";

const mockApi = api as {
  listAccounts: ReturnType<typeof vi.fn>;
  createAccount: ReturnType<typeof vi.fn>;
  updateAccount: ReturnType<typeof vi.fn>;
  removeAccount: ReturnType<typeof vi.fn>;
  openAccount: ReturnType<typeof vi.fn>;
  stopAccount: ReturnType<typeof vi.fn>;
};

const fakeAccount = {
  id: "abc-123",
  name: "Test",
  site: null,
  notes: null,
  tags: [],
  fingerprint_seed: 12345,
  proxy: null,
  timezone: null,
  locale: null,
  platform: "windows",
  user_agent: null,
  screen_width: 1920,
  screen_height: 1080,
  gpu_vendor: null,
  gpu_renderer: null,
  hardware_concurrency: null,
  humanize: false,
  human_preset: "default",
  geoip: false,
  color_scheme: null,
  launch_args: [],
  user_data_dir: "/Users/me/.cloak-accounts/profiles/abc-123",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  status: "stopped" as const,
};

beforeEach(() => {
  mockApi.listAccounts.mockResolvedValue([fakeAccount]);
  mockApi.createAccount.mockResolvedValue(fakeAccount);
  mockApi.updateAccount.mockResolvedValue({ ...fakeAccount, name: "Updated" });
  mockApi.removeAccount.mockResolvedValue(undefined);
  mockApi.openAccount.mockResolvedValue({ account_id: "abc-123", status: "running", pid: 42 });
  mockApi.stopAccount.mockResolvedValue(undefined);
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("useAccounts", () => {
  it("loads accounts on mount", async () => {
    const { result } = renderHook(() => useAccounts());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.accounts).toEqual([fakeAccount]);
    expect(mockApi.listAccounts).toHaveBeenCalled();
  });

  it("create prepends new account", async () => {
    const { result } = renderHook(() => useAccounts());
    await waitFor(() => expect(result.current.loading).toBe(false));

    const newer = { ...fakeAccount, id: "new-1", name: "New" };
    mockApi.createAccount.mockResolvedValueOnce(newer);

    await act(async () => {
      await result.current.create({ name: "New" });
    });

    expect(result.current.accounts[0].id).toBe("new-1");
  });

  it("remove filters account out", async () => {
    const { result } = renderHook(() => useAccounts());
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.remove("abc-123");
    });

    expect(result.current.accounts).toEqual([]);
  });
});
