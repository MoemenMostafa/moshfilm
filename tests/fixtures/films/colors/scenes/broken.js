// A scene whose render throws, for the export-refuses-broken-scene test.
export default {
  setup(root) {
    root.style.background = "#00ff00";
  },
  render() {
    throw new Error("boom in render");
  },
};
