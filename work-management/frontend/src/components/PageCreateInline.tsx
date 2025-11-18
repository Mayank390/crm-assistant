import React, { useEffect, useRef, useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/utils";
import EditorJS from '@editorjs/editorjs';
import Header from '@editorjs/header';
import List from '@editorjs/list';
import Paragraph from '@editorjs/paragraph';
import Table from '@editorjs/table';
import Quote from '@editorjs/quote';
import Code from '@editorjs/code';
import InlineCode from '@editorjs/inline-code';
import LinkTool from '@editorjs/link';
import Marker from '@editorjs/marker';
import Delimiter from '@editorjs/delimiter';
import Embed from '@editorjs/embed';
import ImageTool from '@editorjs/image';
import { Briefcase } from 'lucide-react';
import ProjectSelector from "@/components/ProjectSelector";
import { type Project } from "@/api/projects";

export type PageCreateInlineProps = {
  initialEditorJs?: { blocks: Block[] };
  selectedProject?: Project | null;
  onProjectSelect?: (project: Project | null) => void;
  onSave?: (values: { title: string; editorJs: { blocks: Block[] }; project?: Project | null }) => void;
  onDiscard?: () => void;
  className?: string;
};

interface Block {
  id?: string;
  type: string;
  data: Record<string, unknown>;
}

// Editor.js data format is already compatible, no conversion needed

const FieldChip: React.FC<React.PropsWithChildren<{ icon?: React.ReactNode; onClick?: () => void; className?: string }>> = ({ icon, children, onClick, className }) => (
  <div
    className={cn(
      "inline-flex items-center gap-2 rounded-md border px-3 py-1.5 text-xs text-muted-foreground bg-background",
      onClick && "cursor-pointer hover:bg-muted/50 hover:border-primary/20 transition-colors",
      className
    )}
    onClick={onClick}
  >
    {icon}
    <span className="whitespace-nowrap">{children}</span>
  </div>
);

const Placeholder: React.FC = () => (
  <div className="absolute pointer-events-none text-muted-foreground/70">Write page content…</div>
);

export const PageCreateInline: React.FC<PageCreateInlineProps> = ({
  initialEditorJs,
  selectedProject = null,
  onProjectSelect,
  onSave,
  onDiscard,
  className
}) => {
  const editorRef = useRef<EditorJS | null>(null);
  const editorContainerRef = useRef<HTMLDivElement>(null);
  const [isPreview, setIsPreview] = useState<boolean>(false);
  const [editorData, setEditorData] = useState<{ blocks: Block[] }>(initialEditorJs || {
    blocks: [
      {
        id: 'test-block',
        type: 'paragraph',
        data: {
          text: 'This is a test paragraph to verify the editor is working. If you can see and edit this text, the editor is functioning correctly.'
        }
      }
    ]
  });
  const [editorReady, setEditorReady] = useState<boolean>(false);

  useEffect(() => {

    if (editorContainerRef.current && !editorRef.current) {
      try {
        editorRef.current = new EditorJS({
          holder: editorContainerRef.current,
          data: editorData,
          readOnly: isPreview,
          tools: {
            header: {
              class: Header,
              inlineToolbar: true,
              config: {
                levels: [1, 2, 3, 4, 5, 6],
                defaultLevel: 2
              }
            },
            paragraph: {
              class: Paragraph,
              inlineToolbar: true,
            },
            list: {
              class: List,
              inlineToolbar: true,
            },
            quote: {
              class: Quote,
              inlineToolbar: true,
            },
            code: {
              class: Code,
              inlineToolbar: true,
            },
            inlineCode: {
              class: InlineCode,
              shortcut: 'CMD+SHIFT+M',
            },
            linkTool: {
              class: LinkTool,
              config: {
                endpoint: '/api/fetchUrl',
              }
            },
            marker: {
              class: Marker,
            },
            delimiter: {
              class: Delimiter,
            },
            embed: {
              class: Embed,
              config: {
                services: {
                  youtube: true,
                  coub: true,
                  codepen: true,
                  imgur: true,
                }
              }
            },
            table: Table,
            image: {
              class: ImageTool,
              config: {
                endpoints: {
                  byFile: '/api/uploadFile',
                  byUrl: '/api/fetchUrl',
                }
              }
            },
          },
          placeholder: "Write page content…",
          minHeight: 220,
          autofocus: true,
        });

        editorRef.current.isReady
          .then(() => {
            // Editor.js is ready to work
            setEditorReady(true);
            // Update local state after editor is ready
            setEditorData(initialEditorJs || { blocks: [] });

            // Auto-focus the editor
            if (editorRef.current && editorRef.current.focus) {
              try {
                editorRef.current.focus();
              } catch (error) {
                // Focus method not available
              }
            }
          })
          .catch((reason) => {
            // Editor.js initialization failed
          });
      } catch (error) {
        // Failed to create Editor.js instance
      }
    }

    return () => {
      if (editorRef.current && editorRef.current.destroy) {
        editorRef.current.destroy();
        editorRef.current = null;
      }
    };
  }, []); // Only run once on mount

  // Toggle read-only mode based on isPreview (EditorJS built-in preview)
  useEffect(() => {
    // Persist current content, then rebuild the editor with correct readOnly state.
    let cancelled = false;
    (async () => {
      const holder = editorContainerRef.current;
      if (!holder) return;

      // Save current data if possible
      let nextData = editorData;
      if (editorRef.current?.save) {
        try {
          const output = await editorRef.current.save();
          if (!cancelled) {
            nextData = output as any;
            setEditorData(output as any);
          }
        } catch (e) {
          // fall back to existing state
        }
      }

      // Destroy existing instance
      try {
        editorRef.current?.destroy?.();
      } catch {}
      editorRef.current = null;
      setEditorReady(false);

      // Recreate with updated readOnly
      try {
        const instance = new EditorJS({
          holder,
          data: nextData,
          readOnly: isPreview,
          tools: {
            header: {
              class: Header,
              inlineToolbar: true,
              config: { levels: [1, 2, 3, 4, 5, 6], defaultLevel: 2 },
            },
            paragraph: { class: Paragraph, inlineToolbar: true },
            list: { class: List, inlineToolbar: true },
            quote: { class: Quote, inlineToolbar: true },
            code: { class: Code, inlineToolbar: true },
            inlineCode: { class: InlineCode, shortcut: 'CMD+SHIFT+M' },
            linkTool: { class: LinkTool, config: { endpoint: '/api/fetchUrl' } },
            marker: { class: Marker },
            delimiter: { class: Delimiter },
            embed: { class: Embed, config: { services: { youtube: true, coub: true, codepen: true, imgur: true } } },
            table: Table,
            image: { class: ImageTool, config: { endpoints: { byFile: '/api/uploadFile', byUrl: '/api/fetchUrl' } } },
          },
          placeholder: 'Write page content…',
          minHeight: 400,
          autofocus: !isPreview,
        });
        editorRef.current = instance;
        instance.isReady
          .then(() => {
            if (cancelled) return;
            setEditorReady(true);
            if (!isPreview) {
              try { editorRef.current?.focus?.(); } catch {}
            }
          })
          .catch((err) => {
            // Editor.js (re)initialization failed
          });
      } catch (err) {
        // Failed to rebuild Editor.js instance
      }
    })();

    return () => { cancelled = true; };
  }, [isPreview]);

  // Effect to handle initialEditorJs changes - recreate editor if data changes significantly
  useEffect(() => {
    const hasData = initialEditorJs && initialEditorJs.blocks && initialEditorJs.blocks.length > 0;
    const currentHasData = editorData.blocks && editorData.blocks.length > 0;

    // If the data presence state changed significantly, recreate the editor
    if (hasData !== currentHasData && editorRef.current) {
      if (editorRef.current.destroy) {
        editorRef.current.destroy();
      }
      editorRef.current = null;

      // Reinitialize with new data
      if (editorContainerRef.current) {
        setTimeout(() => {
          if (editorContainerRef.current && !editorRef.current) {
            try {
              editorRef.current = new EditorJS({
                holder: editorContainerRef.current!,
                data: editorData,
                readOnly: isPreview,
                tools: {
                  header: {
                    class: Header,
                    inlineToolbar: true,
                    config: {
                      levels: [1, 2, 3, 4, 5, 6],
                      defaultLevel: 2
                    }
                  },
                  paragraph: {
                    class: Paragraph,
                    inlineToolbar: true,
                  },
                  list: {
                    class: List,
                    inlineToolbar: true,
                  },
                  quote: {
                    class: Quote,
                    inlineToolbar: true,
                  },
                  code: {
                    class: Code,
                    inlineToolbar: true,
                  },
                  inlineCode: {
                    class: InlineCode,
                    shortcut: 'CMD+SHIFT+M',
                  },
                  linkTool: {
                    class: LinkTool,
                    config: {
                      endpoint: '/api/fetchUrl',
                    }
                  },
                  marker: {
                    class: Marker,
                  },
                  delimiter: {
                    class: Delimiter,
                  },
                  embed: {
                    class: Embed,
                    config: {
                      services: {
                        youtube: true,
                        coub: true,
                        codepen: true,
                        imgur: true,
                      }
                    }
                  },
                  table: Table,
                  image: {
                    class: ImageTool,
                    config: {
                      endpoints: {
                        byFile: '/api/uploadFile',
                        byUrl: '/api/fetchUrl',
                      }
                    }
                  },
                },
                placeholder: "Write page content…",
                minHeight: 400,
                autofocus: true,
              });

              editorRef.current.isReady
                .then(() => {
                  // Editor.js recreated and ready
                  setEditorReady(true);
                  setEditorData(initialEditorJs || { blocks: [] });

                  // Auto-focus the editor
                  if (editorRef.current && editorRef.current.focus) {
                    try {
                      editorRef.current.focus();
                    } catch (error) {
                      // Focus method not available
                    }
                  }
                })
                .catch((error) => {
                  // Failed to recreate Editor.js
                });
            } catch (error) {
              // Failed to create new Editor.js instance
            }
          }
        }, 100);
      }
    } else if (initialEditorJs) {
      // Just update the state if only content changed
      setEditorData(initialEditorJs);
    }
  }, [initialEditorJs]);

  const handleSave = async () => {
    if (editorRef.current) {
      try {
        const outputData = await editorRef.current.save();
        setEditorData(outputData);
        onSave?.({ title: "Untitled Page", editorJs: outputData, project: selectedProject });
      } catch (error) {
        // Saving failed
      }
    }
  };

  // No separate preview renderer needed; we use EditorJS read-only mode

  // Markdown conversion removed; EditorJS read-only view is used for preview

  return (
    <Card className={cn("border-muted/70 shadow-lg", className)}>
      <CardContent className="p-0">

        <div className="px-8 pt-8 pb-4">
          <div className="flex items-center justify-end gap-3">
            <span className={cn("text-sm font-medium", !isPreview && "text-foreground", isPreview && "text-muted-foreground")}>Edit</span>
            <Switch checked={isPreview} onCheckedChange={(v) => setIsPreview(Boolean(v))} />
            <span className={cn("text-sm font-medium", isPreview && "text-foreground", !isPreview && "text-muted-foreground")}>Preview</span>
          </div>
          <div className="mt-6 relative">
            <div
              ref={editorContainerRef}
              className="border-2 rounded-lg bg-background min-h-[400px] max-h-[600px] overflow-auto editor-container"
              style={{
                padding: '55px',
                fontSize: '15px',
                lineHeight: '1.7',
                border: '2px solid hsl(var(--border))',
                backgroundColor: 'hsl(var(--background))',
                color: 'hsl(var(--foreground))',
              }}
              aria-busy={!editorReady}
            />
            {!editorReady && (
              <div className="absolute inset-0 flex items-center justify-center rounded-lg bg-background/60 backdrop-blur-[1px]">
              </div>
            )}
          </div>
        </div>

        <div className="px-8 py-6 border-t-2 flex items-center justify-between gap-3 bg-muted/20">
          <ProjectSelector
            selectedProject={selectedProject}
            onProjectSelect={onProjectSelect}
            trigger={(
              <FieldChip
                icon={<Briefcase className="h-3.5 w-3.5" />}
                className={selectedProject ? "text-foreground border-primary/20 bg-primary/5" : undefined}
              >
                {selectedProject ? `${selectedProject.projectName} (${selectedProject.projectDisplayId})` : "Project"}
              </FieldChip>
            )}
          />
          <Button onClick={handleSave} size="lg" className="px-8">Save Page</Button>
        </div>
      </CardContent>
    </Card>
  );
};

export default PageCreateInline;

