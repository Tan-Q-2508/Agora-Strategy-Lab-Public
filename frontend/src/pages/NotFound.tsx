import { Compass } from "lucide-react";
import { Link } from "react-router";
import { EmptyState } from "../components/states";
import { Button } from "../components/ui/button";
import { Card } from "../components/ui/card";

export default function NotFound() {
  return (
    <Card className="min-h-[420px] justify-center">
      <EmptyState
        icon={Compass}
        title="That page doesn't exist"
        body="The link may be old. Everything is reachable from the menu on the left."
        action={
          <Button variant="soft" asChild>
            <Link to="/">Go home</Link>
          </Button>
        }
      />
    </Card>
  );
}
