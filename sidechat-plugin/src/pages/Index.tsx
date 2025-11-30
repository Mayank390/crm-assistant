import { ChatSidebar } from "@/components/ChatSidebar";

const Index = () => {
  return (
    <div className="flex h-screen bg-background">
      {/* Main Content Area */}
      <div className="flex-1 flex items-center justify-center p-8">
        <div className="max-w-2xl text-center">
          <h1 className="text-4xl font-bold mb-4 bg-gradient-to-r from-primary to-accent bg-clip-text text-transparent">
            AI Lead Assistant
          </h1>
          <p className="text-xl text-muted-foreground mb-6">
            Your intelligent sidekick for lead management and customer conversations
          </p>
          <div className="text-left space-y-4 bg-muted/30 rounded-lg p-6">
            <div className="flex items-start gap-3">
              <div className="w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center flex-shrink-0">
                <span className="text-primary font-bold">1</span>
              </div>
              <div>
                <h3 className="font-semibold mb-1">Smart Conversations</h3>
                <p className="text-sm text-muted-foreground">
                  Get AI-powered insights and recommendations based on lead history
                </p>
              </div>
            </div>
            <div className="flex items-start gap-3">
              <div className="w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center flex-shrink-0">
                <span className="text-primary font-bold">2</span>
              </div>
              <div>
                <h3 className="font-semibold mb-1">Quick Actions</h3>
                <p className="text-sm text-muted-foreground">
                  Summarize, draft messages, or prepare for meetings with one click
                </p>
              </div>
            </div>
            <div className="flex items-start gap-3">
              <div className="w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center flex-shrink-0">
                <span className="text-primary font-bold">3</span>
              </div>
              <div>
                <h3 className="font-semibold mb-1">Always Available</h3>
                <p className="text-sm text-muted-foreground">
                  Access your AI assistant anytime from the convenient sidepanel
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Chat Sidebar */}
      <div className="w-[400px]">
        <ChatSidebar />
      </div>
    </div>
  );
};

export default Index;
