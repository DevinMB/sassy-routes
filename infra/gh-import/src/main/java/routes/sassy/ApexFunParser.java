package routes.sassy;

import com.graphhopper.reader.ReaderWay;
import com.graphhopper.routing.ev.DecimalEncodedValue;
import com.graphhopper.routing.ev.EdgeIntAccess;
import com.graphhopper.routing.util.parsers.TagParser;
import com.graphhopper.storage.IntsRef;

import java.util.Map;

/** Sets apex_fun on each edge from the pipeline's way_id → fun×100 map. */
public class ApexFunParser implements TagParser {
    private final DecimalEncodedValue ev;
    private final Map<Long, Integer> scores;
    private final double defaultFun;

    public ApexFunParser(DecimalEncodedValue ev, Map<Long, Integer> scores, double defaultFun) {
        this.ev = ev;
        this.scores = scores;
        this.defaultFun = defaultFun;
    }

    @Override
    public void handleWayTags(int edgeId, EdgeIntAccess edgeIntAccess, ReaderWay way, IntsRef relationFlags) {
        Integer bucket = scores.get(way.getId());
        double fun = bucket == null ? defaultFun : bucket / 100.0;
        ev.setDecimal(false, edgeId, edgeIntAccess, Math.max(0.0, Math.min(1.0, fun)));
    }
}
