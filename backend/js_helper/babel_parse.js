/**
 * Called by Python (app/jsx_parser.py) as:
 *   node babel_parse.js <absolute-file-path>
 *
 * Prints ONE line of JSON to stdout:
 *   { imports: [...], classNameUsages: [...] }
 * or on a parse failure:
 *   { error: "message" }
 *
 * This script only EXTRACTS data. It does not decide what's a conflict —
 * that's Phase 4 (static analysis), reading this output from Python.
 */
const fs = require("fs");
const parser = require("@babel/parser");
const traverse = require("@babel/traverse").default;
const generate = require("@babel/generator").default;

const filePath = process.argv[2];
const code = fs.readFileSync(filePath, "utf8");

let ast;
try {
  ast = parser.parse(code, {
    sourceType: "module",
    plugins: [
      "jsx",
      "classProperties",
      "optionalChaining",
      "nullishCoalescingOperator",
    ],
  });
} catch (err) {
  console.log(JSON.stringify({ error: err.message }));
  process.exit(0);
}

const imports = [];
const classNameUsages = [];

/**
 * Walks a className value expression and does its best to resolve it into
 * known class name strings, even through common dynamic patterns:
 *   - "foo"                                  -> static
 *   - `foo ${x}`                              -> "foo" static, x flagged dynamic
 *   - clsx("foo", cond && "bar", {baz: cond}) -> foo/bar/baz all extracted
 *   - cond ? "a" : "b"                        -> both "a" and "b" extracted
 * Anything it truly can't resolve (a bare variable, function call it
 * doesn't recognize, etc.) is kept as raw source text in dynamicExpression
 * so nothing is silently dropped — Phase 4 can decide how to treat it.
 */
function extractFromClassNameValue(valueNode) {
  const staticClasses = [];
  const dynamicParts = [];
  let fullyStatic = true;

  function addStringLiteralText(text) {
    text.split(/\s+/).filter(Boolean).forEach((c) => staticClasses.push(c));
  }

  function handleNode(node) {
    if (!node) return;

    switch (node.type) {
      case "StringLiteral":
        addStringLiteralText(node.value);
        break;

      case "TemplateLiteral":
        node.quasis.forEach((q) => addStringLiteralText(q.value.raw));
        if (node.expressions.length > 0) {
          fullyStatic = false;
          node.expressions.forEach((e) => dynamicParts.push(generate(e).code));
        }
        break;

      case "CallExpression": {
        const calleeName =
          node.callee.name || (node.callee.property && node.callee.property.name);
        const isClassNameHelper = ["clsx", "classnames", "cn"].includes(calleeName);

        if (isClassNameHelper) {
          node.arguments.forEach((arg) => {
            if (arg.type === "StringLiteral") {
              addStringLiteralText(arg.value);
            } else if (arg.type === "ObjectExpression") {
              arg.properties.forEach((prop) => {
                if (!prop.key || prop.computed) {
                  fullyStatic = false;
                  return;
                }
                const keyName = prop.key.name || prop.key.value;
                if (keyName) {
                  fullyStatic = false; // conditional — name known, but applied conditionally
                  staticClasses.push(keyName);
                }
              });
            } else {
              fullyStatic = false;
              dynamicParts.push(generate(arg).code);
            }
          });
        } else {
          fullyStatic = false;
          dynamicParts.push(generate(node).code);
        }
        break;
      }

      case "LogicalExpression":
        if (node.operator === "&&") {
          fullyStatic = false;
          if (node.right.type === "StringLiteral") {
            addStringLiteralText(node.right.value);
          } else {
            dynamicParts.push(generate(node.right).code);
          }
        } else {
          fullyStatic = false;
          dynamicParts.push(generate(node).code);
        }
        break;

      case "ConditionalExpression":
        fullyStatic = false;
        if (node.consequent.type === "StringLiteral") {
          addStringLiteralText(node.consequent.value);
        } else {
          dynamicParts.push(generate(node.consequent).code);
        }
        if (node.alternate.type === "StringLiteral") {
          addStringLiteralText(node.alternate.value);
        } else {
          dynamicParts.push(generate(node.alternate).code);
        }
        break;

      default:
        fullyStatic = false;
        dynamicParts.push(generate(node).code);
    }
  }

  handleNode(valueNode);

  return {
    staticClasses: [...new Set(staticClasses)],
    dynamicExpression: dynamicParts.length > 0 ? dynamicParts.join(" | ") : null,
    isFullyStatic: fullyStatic,
  };
}

traverse(ast, {
  ImportDeclaration(path) {
    const source = path.node.source.value;
    const specifiers = path.node.specifiers.map((spec) => {
      if (spec.type === "ImportDefaultSpecifier") {
        return { imported_name: null, local_name: spec.local.name, import_type: "default" };
      } else if (spec.type === "ImportNamespaceSpecifier") {
        return { imported_name: null, local_name: spec.local.name, import_type: "namespace" };
      }
      return {
        imported_name: spec.imported.name,
        local_name: spec.local.name,
        import_type: "named",
      };
    });

    imports.push({
      source,
      specifiers,
      line_number: path.node.loc.start.line,
      is_css_import: source.endsWith(".css"),
    });
  },

  JSXOpeningElement(path) {
    const elementName = path.node.name.name || "Unknown";
    const classNameAttr = path.node.attributes.find(
      (attr) => attr.type === "JSXAttribute" && attr.name && attr.name.name === "className"
    );
    if (!classNameAttr) return;

    let result;
    if (classNameAttr.value === null) {
      result = { staticClasses: [], dynamicExpression: null, isFullyStatic: true };
    } else if (classNameAttr.value.type === "StringLiteral") {
      result = extractFromClassNameValue(classNameAttr.value);
    } else if (classNameAttr.value.type === "JSXExpressionContainer") {
      result = extractFromClassNameValue(classNameAttr.value.expression);
    } else {
      result = { staticClasses: [], dynamicExpression: null, isFullyStatic: true };
    }

    classNameUsages.push({
      element: elementName,
      line_number: path.node.loc.start.line,
      static_classes: result.staticClasses,
      dynamic_expression: result.dynamicExpression,
      is_fully_static: result.isFullyStatic,
    });
  },
});

console.log(JSON.stringify({ imports, classNameUsages }));
