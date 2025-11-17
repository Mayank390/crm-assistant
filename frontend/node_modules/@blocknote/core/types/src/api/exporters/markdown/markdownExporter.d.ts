import { Schema } from "prosemirror-model";
import { Block } from "../../../blocks/defaultBlocks";
import type { BlockNoteEditor } from "../../../editor/BlockNoteEditor";
import { BlockSchema, InlineContentSchema, StyleSchema } from "../../../schema";
export declare function cleanHTMLToMarkdown(cleanHTMLString: string): string;
export declare function blocksToMarkdown<BSchema extends BlockSchema, I extends InlineContentSchema, S extends StyleSchema>(blocks: Block<BSchema, I, S>[], schema: Schema, editor: BlockNoteEditor<BSchema, I, S>): string;
