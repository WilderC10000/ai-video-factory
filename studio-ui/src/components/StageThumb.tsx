import { isVideo } from "../format";
import type { Stage } from "../types";

interface Props {
  stage: Stage;
  controls?: boolean;
  className?: string;
}

/** Real output of a stage (still or clip), or an honest empty state. */
export function StageThumb({ stage, controls = false, className = "" }: Props) {
  if (stage.latest_output_url) {
    return isVideo(stage) ? (
      <span className={`thumb-video ${className}`}>
        {/* Poster = the clip's real start frame, so the tile is never blank before the video decodes. */}
        <video
          className="thumb"
          src={`${stage.latest_output_url}#t=0.5`}
          poster={stage.previous_frame_url ?? undefined}
          muted
          playsInline
          preload="metadata"
          controls={controls}
        />
        {!controls && <span className="thumb-video__badge">▶</span>}
      </span>
    ) : (
      <img className={`thumb ${className}`} src={stage.latest_output_url} alt={stage.label} loading="lazy" />
    );
  }
  const text =
    stage.latest_output_exists === false ? "File missing" : stage.status === "complete" ? "No file output" : "Not generated";
  return <div className={`thumb thumb--empty ${className}`}>{text}</div>;
}
