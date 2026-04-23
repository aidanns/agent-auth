import conventionalcommits from "conventional-changelog-conventionalcommits";

// The conventionalcommits preset appends two extra pieces to each entry:
//   1. a `([<shortHash>](<commitUrl>))` link — redundant with the PR link
//      that the preset derives from the squash-merge subject.
//   2. a `, closes [#NN](...)` footer listing issue references from the
//      commit body — noisy in the changelog; the PR already links the
//      closed issues.
// Strip both blocks from the preset's commitPartial.
const preset = await conventionalcommits({});
const commitPartial = preset.writer.commitPartial
  .replace(/\{\{~!-- commit link --\}\}[\s\S]*?\{\{~\/if\}\}\{\{~\/if\}\}\n/, "")
  .replace(/\{\{~!-- commit references --\}\}[\s\S]*$/, "");

export default {
  branches: ["main"],
  tagFormat: "v${version}",
  plugins: [
    [
      "@semantic-release/commit-analyzer",
      {
        preset: "conventionalcommits",
        releaseRules: [
          { breaking: true, release: "minor" },
          { type: "feat", release: "minor" },
          { type: "fix", release: "patch" },
          { type: "perf", release: "patch" },
          { type: "revert", release: "patch" },
          { type: "docs", release: false },
          { type: "style", release: false },
          { type: "chore", release: false },
          { type: "refactor", release: false },
          { type: "test", release: false },
          { type: "build", release: false },
          { type: "ci", release: false },
        ],
      },
    ],
    [
      "@semantic-release/release-notes-generator",
      {
        preset: "conventionalcommits",
        writerOpts: { commitPartial },
      },
    ],
    [
      "@semantic-release/changelog",
      {
        changelogFile: "CHANGELOG.md",
        changelogTitle: "# Changelog",
      },
    ],
    [
      "@semantic-release/exec",
      {
        prepareCmd: "task format",
      },
    ],
    [
      "@semantic-release/github",
      {
        failComment: false,
      },
    ],
    [
      "@semantic-release/git",
      {
        assets: ["CHANGELOG.md"],
        message: "chore(release): ${nextRelease.version}\n\n${nextRelease.notes}",
      },
    ],
  ],
};
