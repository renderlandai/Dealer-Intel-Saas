import { describe, it, expect } from "vitest";
import { parseCsv, parseCsvWithHeaders } from "./csv";

describe("parseCsv", () => {
  it("parses simple comma-separated rows", () => {
    expect(parseCsv("a,b,c\n1,2,3\n")).toEqual([
      ["a", "b", "c"],
      ["1", "2", "3"],
    ]);
  });

  it("handles quoted fields containing commas", () => {
    expect(parseCsv('name,desc\n"Acme, Inc.","sells, things"\n')).toEqual([
      ["name", "desc"],
      ["Acme, Inc.", "sells, things"],
    ]);
  });

  it("handles escaped double quotes", () => {
    expect(parseCsv('name\n"He said ""hi"""\n')).toEqual([["name"], ['He said "hi"']]);
  });

  it("handles CRLF line endings", () => {
    expect(parseCsv("a,b\r\n1,2\r\n")).toEqual([
      ["a", "b"],
      ["1", "2"],
    ]);
  });

  it("handles file with no trailing newline", () => {
    expect(parseCsv("a,b\n1,2")).toEqual([
      ["a", "b"],
      ["1", "2"],
    ]);
  });

  it("returns empty array for empty input", () => {
    expect(parseCsv("")).toEqual([]);
  });
});

describe("parseCsvWithHeaders", () => {
  it("normalizes headers and maps rows", () => {
    const result = parseCsvWithHeaders("Name,Website URL\nAcme,https://acme.com\n");
    expect(result.headers).toEqual(["name", "website_url"]);
    expect(result.rows).toEqual([{ name: "Acme", website_url: "https://acme.com" }]);
  });

  it("trims cell values", () => {
    const result = parseCsvWithHeaders("name\n  Acme  \n");
    expect(result.rows[0].name).toBe("Acme");
  });

  it("fills missing trailing columns with empty strings", () => {
    const result = parseCsvWithHeaders("name,region\nAcme\n");
    expect(result.rows[0]).toEqual({ name: "Acme", region: "" });
  });
});
