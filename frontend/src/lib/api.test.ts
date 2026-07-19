import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("@tauri-apps/api/core", () => ({
  invoke: vi.fn(),
}));

import { invoke } from "@tauri-apps/api/core";
import { api } from "./api";

const mockInvoke = invoke as ReturnType<typeof vi.fn>;

beforeEach(() => {
  mockInvoke.mockReset();
});

describe("api.listAccounts", () => {
  it("invokes list_accounts", async () => {
    const accounts = [{ id: "1", name: "Test", status: "stopped" }];
    mockInvoke.mockResolvedValueOnce(accounts);
    const result = await api.listAccounts();
    expect(result).toEqual(accounts);
    expect(mockInvoke).toHaveBeenCalledWith("list_accounts", undefined);
  });
});

describe("api.createAccount", () => {
  it("invokes create_account with payload", async () => {
    const account = { id: "2", name: "New", status: "stopped" };
    mockInvoke.mockResolvedValueOnce(account);
    await api.createAccount({ name: "New" });
    expect(mockInvoke).toHaveBeenCalledWith("create_account", {
      payload: { name: "New" },
    });
  });
});

describe("api.updateAccount", () => {
  it("invokes update_account with id and payload", async () => {
    mockInvoke.mockResolvedValueOnce({ id: "1", name: "Updated" });
    await api.updateAccount("1", { name: "Updated" });
    expect(mockInvoke).toHaveBeenCalledWith("update_account", {
      id: "1",
      payload: { name: "Updated" },
    });
  });
});

describe("api.removeAccount", () => {
  it("invokes remove_account", async () => {
    mockInvoke.mockResolvedValueOnce(undefined);
    await api.removeAccount("1");
    expect(mockInvoke).toHaveBeenCalledWith("remove_account", { id: "1" });
  });
});

describe("api.openAccount", () => {
  it("invokes open_account", async () => {
    const result = { account_id: "1", status: "running", pid: 1234 };
    mockInvoke.mockResolvedValueOnce(result);
    const data = await api.openAccount("1");
    expect(data).toEqual(result);
    expect(mockInvoke).toHaveBeenCalledWith("open_account", { id: "1", url: null });
  });
});

describe("api.stopAccount", () => {
  it("invokes stop_account", async () => {
    mockInvoke.mockResolvedValueOnce(undefined);
    await api.stopAccount("1");
    expect(mockInvoke).toHaveBeenCalledWith("stop_account", { id: "1" });
  });
});

// Back-compat aliases
describe("api profile aliases", () => {
  it("listProfiles maps to list_accounts", async () => {
    mockInvoke.mockResolvedValueOnce([]);
    await api.listProfiles();
    expect(mockInvoke).toHaveBeenCalledWith("list_accounts", undefined);
  });

  it("launchProfile maps to open_account", async () => {
    mockInvoke.mockResolvedValueOnce({ account_id: "1", status: "running", pid: 1 });
    await api.launchProfile("1");
    expect(mockInvoke).toHaveBeenCalledWith("open_account", { id: "1", url: null });
  });
});
