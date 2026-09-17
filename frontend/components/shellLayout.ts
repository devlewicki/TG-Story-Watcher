/**
 * Shared layout geometry for the user AppShell and the admin AdminShell.
 *
 * Both shells MUST use these values so the user pages and admin pages have
 * exactly the same content width, side padding, top-bar height and bottom
 * spacing — nothing should visually shift when switching between them.
 */

/** Width of the fixed left sidebar (both shells). */
export const SIDEBAR_WIDTH = 64; // rem — w-64

/** Top bar height (both shells). */
export const TOPBAR_HEIGHT = 16; // rem — h-16

/**
 * Classes for the centered content container (<main>) in both shells.
 * max-w-6xl + identical horizontal padding and bottom spacing everywhere,
 * so the admin page is never wider or shifted compared to the user page.
 */
export const SHELL_MAIN_CLASSES =
  "mx-auto w-full max-w-6xl px-4 pb-24 pt-4 sm:px-6 sm:py-6";

/** Top bar classes shared by both shells (sticky, same height/padding). */
export const SHELL_TOPBAR_CLASSES =
  "sticky top-0 z-10 flex h-16 items-center justify-between border-b border-slate-200/70 bg-white/70 px-4 backdrop-blur-md dark:border-slate-800 dark:bg-slate-950/70 sm:px-6";

/** Offset applied to the content wrapper below the fixed sidebar (both shells). */
export const SHELL_CONTENT_OFFSET_CLASSES = "md:pl-64";
