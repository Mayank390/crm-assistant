import { Fragment, Schema } from "prosemirror-model";
import { PartialBlock } from "../../../blocks/defaultBlocks";
import type { BlockNoteEditor } from "../../../editor/BlockNoteEditor";
import { BlockSchema, InlineContentSchema, StyleSchema } from "../../../schema";
export interface InternalHTMLSerializer<BSchema extends BlockSchema, I extends InlineContentSchema, S extends StyleSchema> {
    serializeProseMirrorFragment: (fragment: Fragment) => string;
    serializeBlocks: (blocks: PartialBlock<BSchema, I, S>[]) => string;
}
export declare const createInternalHTMLSerializer: <BSchema extends Record<string, import("../../../schema").BlockConfig>, I extends InlineContentSchema, S extends StyleSchema>(schema: Schema, editor: BlockNoteEditor<BSchema, I, S>) => InternalHTMLSerializer<BSchema, I, S>;
