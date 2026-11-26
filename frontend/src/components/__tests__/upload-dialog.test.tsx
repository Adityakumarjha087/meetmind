import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { UploadDialog } from "@/components/upload-dialog";
import { api } from "@/lib/api";
import type { MeetingDetail } from "@/lib/types";

describe("UploadDialog", () => {
  it("requires a file, then uploads with title and transcript", async () => {
    const onUploaded = vi.fn();
    const spy = vi.spyOn(api, "uploadMeeting").mockResolvedValue({ id: "m1" } as MeetingDetail);
    render(<UploadDialog workspaceId="w1" onUploaded={onUploaded} />);
    await userEvent.click(screen.getByRole("button", { name: "New meeting" }));
    await userEvent.click(screen.getByRole("button", { name: "Upload & process" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Choose or record");

    await userEvent.type(screen.getByLabelText("Title"), "Weekly sync");
    const audio = new File(["RIFF"], "sync.wav", { type: "audio/wav" });
    await userEvent.upload(screen.getByLabelText("Audio or video file"), audio);
    await userEvent.click(screen.getByRole("button", { name: "Upload & process" }));
    expect(spy).toHaveBeenCalledTimes(1);
    const form = spy.mock.calls[0][1];
    expect(form.get("title")).toBe("Weekly sync");
    expect((form.get("file") as File).name).toBe("sync.wav");
    expect(form.get("source")).toBe("upload");
    expect(onUploaded).toHaveBeenCalledWith({ id: "m1" });
  });
});
