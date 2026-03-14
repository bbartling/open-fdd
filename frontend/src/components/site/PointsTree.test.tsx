import { describe, it, expect } from "vitest";
import { POINTS_CONTEXT_MENU_TEST_IDS } from "./PointsTree";

/** Labels shown in point context menu (E2E and tests rely on these). */
const POINT_CONTEXT_MENU_LABELS = {
  POLL_TRUE: "Poll true",
  POLL_FALSE: "Poll false",
  DELETE_POINT: "Delete point",
} as const;

describe("PointsTree", () => {
  describe("POINTS_CONTEXT_MENU_TEST_IDS", () => {
    it("exposes test ids used by E2E for point context menu", () => {
      expect(POINTS_CONTEXT_MENU_TEST_IDS.POLL_TRUE).toBe(
        "points-context-menu-poll-true",
      );
      expect(POINTS_CONTEXT_MENU_TEST_IDS.POLL_FALSE).toBe(
        "points-context-menu-poll-false",
      );
      expect(POINTS_CONTEXT_MENU_TEST_IDS.DELETE_POINT).toBe(
        "points-context-menu-delete-point",
      );
    });

    it("exposes delete test ids for equipment and site", () => {
      expect(POINTS_CONTEXT_MENU_TEST_IDS.DELETE_EQUIPMENT).toBe(
        "points-context-menu-delete-equipment",
      );
      expect(POINTS_CONTEXT_MENU_TEST_IDS.DELETE_SITE).toBe(
        "points-context-menu-delete-site",
      );
    });
  });

  describe("point context menu labels", () => {
    it("uses Poll true, Poll false, Delete point for E2E", () => {
      expect(POINT_CONTEXT_MENU_LABELS.POLL_TRUE).toBe("Poll true");
      expect(POINT_CONTEXT_MENU_LABELS.POLL_FALSE).toBe("Poll false");
      expect(POINT_CONTEXT_MENU_LABELS.DELETE_POINT).toBe("Delete point");
    });
  });
});
