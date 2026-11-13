// A scene whose render throws: the layout check must report it and carry on.
export default {
  setup(root) {
    root.style.background = "#eee";
  },
  render() {
    throw new Error("boom in render");
  },
};
