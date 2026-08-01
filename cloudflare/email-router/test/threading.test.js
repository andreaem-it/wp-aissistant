import test from "node:test";
import assert from "node:assert/strict";
import { normalizeMessageId, rootThreadId, shouldIgnore } from "../src/threading.js";

test("keeps stable root",()=>assert.equal(rootThreadId("<new>","<reply>","<root> <reply>"),"<root>"));
test("falls back",()=>{assert.equal(rootThreadId("<new>","<reply>",""),"<reply>");assert.equal(rootThreadId("<new>","",""),"<new>");});
test("strips newlines",()=>assert.equal(normalizeMessageId("<root>\r\nX-Bad: yes"),"<root>  X-Bad: yes"));
test("ignores automated mail",()=>{const h=new Headers();assert.equal(shouldIgnore(h,"support@wpaissistant.it","support@wpaissistant.it"),true);h.set("auto-submitted","auto-replied");assert.equal(shouldIgnore(h,"person@example.it","support@wpaissistant.it"),true);});
