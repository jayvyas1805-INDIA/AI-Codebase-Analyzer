"""
Generates a synthetic 'real-world-messy' project to reproduce the exact
regressions reported:
  1. Speed: hundreds of files all defining a common utility class name
     (.container), which used to trigger O(files^2) clustering.
  2. Correctness: a real, same-app conflict (.header-bg defined twice
     with different colors, both used in JSX) inside a project where
     import resolution deliberately can't fully trace every file (some
     imports use path aliases / are simply omitted), simulating what a
     real complex codebase's import graph looks like when tracing gaps up.

Run: python generate_big_fixture.py
"""
import os
import shutil

ROOT = "big_fixture_project"


def main():
    if os.path.exists(ROOT):
        shutil.rmtree(ROOT)
    os.makedirs(f"{ROOT}/src/components")

    # No package.json at all, no src/ boundary trick beyond the one that
    # already exists -> single_app_fallback, exactly like a real messy
    # "just a src/ folder" upload.
    with open(f"{ROOT}/src/index.js", "w") as f:
        f.write('import "./App.js";\n')
    with open(f"{ROOT}/src/App.js", "w") as f:
        f.write(
            'import HeaderA from "./components/HeaderA.jsx";\n'
            'import HeaderB from "./components/HeaderB.jsx";\n'
            'export default function App() {\n'
            '  return <div><HeaderA /><HeaderB /></div>;\n'
            '}\n'
        )

    # 300 unrelated components, each with their own CSS file defining the
    # SAME common utility class name '.container' — this is what used to
    # blow up O(files^2). None of these are ever imported by App.js on
    # purpose, simulating "the import graph has gaps" (real projects often
    # have components imported via path aliases jsx_parser can't resolve).
    for i in range(300):
        with open(f"{ROOT}/src/components/Widget{i}.jsx", "w") as f:
            f.write(
                f'import "./Widget{i}.css";\n'
                f'export default function Widget{i}() {{\n'
                f'  return <div className="container">Widget {i}</div>;\n'
                f'}}\n'
            )
        with open(f"{ROOT}/src/components/Widget{i}.css", "w") as f:
            f.write(".container {\n  padding: 8px;\n}\n")

    # The genuine real conflict: two DIFFERENT files, same app, same
    # import-graph gap situation, defining '.header-bg' with conflicting
    # colors, and BOTH are actually used.
    with open(f"{ROOT}/src/components/HeaderA.jsx", "w") as f:
        f.write(
            'import "./HeaderA.css";\n'
            'export default function HeaderA() {\n'
            '  return <div className="header-bg">A</div>;\n'
            '}\n'
        )
    with open(f"{ROOT}/src/components/HeaderA.css", "w") as f:
        f.write(".header-bg {\n  background: red;\n  color: white;\n}\n")

    with open(f"{ROOT}/src/components/HeaderB.jsx", "w") as f:
        f.write(
            'import "./HeaderB.css";\n'
            'export default function HeaderB() {\n'
            '  return <div className="header-bg">B</div>;\n'
            '}\n'
        )
    with open(f"{ROOT}/src/components/HeaderB.css", "w") as f:
        f.write(".header-bg {\n  background: blue;\n  color: black;\n}\n")

    print(f"Generated {ROOT}/ with 300 Widget components + a real HeaderA/HeaderB conflict.")


if __name__ == "__main__":
    main()
