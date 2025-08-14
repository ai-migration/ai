package egovframework.dev.kw3c.handlers;

import org.eclipse.core.commands.AbstractHandler;
import org.eclipse.core.commands.ExecutionEvent;
import org.eclipse.core.commands.ExecutionException;
import org.eclipse.core.runtime.Path;

import egovframework.dev.kw3c.Kw3cPlugin;

public class Kw3cExecuteHandler extends AbstractHandler {

	public Object execute(ExecutionEvent event) throws ExecutionException {
		try {
			Path path = new Path(Kw3cPlugin.getDefault().getInstalledPath());
			String exeFileName = path.append("KW3CValidator/" + "KW3C.exe").toOSString();
			Runtime runtime = Runtime.getRuntime();
			@SuppressWarnings("unused")
			Process prc = runtime.exec(exeFileName);
		} catch (Exception e) {
			e.printStackTrace();
		}
		return null;
	}

}
