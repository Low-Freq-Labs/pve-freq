(function(global){
  'use strict';

  function create(options){
    options=options||{};
    var doc=options.document||global.document;
    var history=options.history||global.history;
    var location=options.location||global.location;
    var loaders=options.loaders||{};
    var aliases=options.aliases||{};
    var viewIds=options.viewIds||[];
    var viewToNav=options.viewToNav||{};
    var viewTitles=options.viewTitles||{};
    var navTitles=options.navTitles||{};

    function resolve(view){
      // Only declared string routes and aliases may select an original loader.
      // History data must never run a caller-supplied coercion during resolution.
      if(typeof view!=='string')return 'home';
      if(Object.prototype.hasOwnProperty.call(aliases,view)){
        view=aliases[view];
        if(typeof view!=='string')return 'home';
      }
      return Object.prototype.hasOwnProperty.call(loaders,view)&&typeof loaders[view]==='function'?view:'home';
    }

    function fromLocation(){
      var path=location.pathname.replace(/^\/dashboard\/?/,'').replace(/^\/+|\/+$/g,'');
      return resolve(path||'home');
    }

    function switchView(requested,skipPush){
      var routeTicket=options.reserveTransition?options.reserveTransition():null;
      function current(){return !options.isTransitionCurrent||options.isTransitionCurrent(routeTicket);}
      var view=resolve(requested);
      if(!current())return view;
      var transition=options.beforeTransition?options.beforeTransition(view):null;
      if(!current())return view;
      if(options.beforeSwitch)options.beforeSwitch();
      if(!current())return view;
      if(options.setCurrentView)options.setCurrentView(view);
      if(!current())return view;

      viewIds.forEach(function(id){
        var viewElement=doc.getElementById(id+'-view');
        if(!current())return;
        if(viewElement){if(id==='fleet'&&options.hideOriginalFleet)options.hideOriginalFleet(routeTicket,viewElement);else viewElement.style.display='none';if(id==='pve-firewall'){viewElement.hidden=true;viewElement.inert=true;}}
      });
      var activeView=doc.getElementById(view+'-view');
      if(!current())return view;
      if(activeView){if(view==='pve-firewall'){activeView.hidden=false;activeView.inert=false;activeView.classList.remove('d-none');}if(view==='fleet'&&options.showOriginalFleet)options.showOriginalFleet(routeTicket,activeView);else activeView.style.display='block';}

      var navGroup=viewToNav[view]||view;
      if(!current())return view;
      doc.querySelectorAll('.view-btn').forEach(function(button){
        if(!current())return;
        if(options.fleetNavWriter&&button.getAttribute('data-view')==='fleet')options.fleetNavWriter.unmark(routeTicket,button);else button.classList.remove('active-view');
        if(!current())return;
        if(options.fleetNavWriter&&button.getAttribute('data-view')==='fleet')options.fleetNavWriter.clear(routeTicket,button);else button.removeAttribute('aria-current');
      });
      if(!current())return view;
      var activeButton=doc.querySelector('.view-btn[data-view="'+navGroup+'"]');
      if(!current())return view;
      if(activeButton){
        if(options.fleetNavWriter&&activeButton.getAttribute('data-view')==='fleet')options.fleetNavWriter.mark(routeTicket,activeButton);else activeButton.classList.add('active-view');
        if(!current())return view;
        if(options.fleetNavWriter&&activeButton.getAttribute('data-view')==='fleet')options.fleetNavWriter.page(routeTicket,activeButton);else activeButton.setAttribute('aria-current','page');
      }
      if(!current())return view;

      var title=doc.getElementById('page-title');
      var specificTitle=viewTitles[view]||navTitles[navGroup]||view;
      if(options.setTitle)options.setTitle(specificTitle);
      else if(title)title.textContent=specificTitle;
      if(!current())return view;
      var tagline=doc.getElementById('header-tagline');
      if(tagline&&options.tagline){var subtitle=options.tagline(navGroup);if(!current())return view;tagline.textContent=subtitle;}
      if(!current())return view;
      if(options.refreshHeader)options.refreshHeader();
      if(!current())return view;

      if(!skipPush){
        try{history.pushState({view:view},'','/dashboard/'+view);}catch(e){}
      }
      if(!current())return view;
      if(options.afterTransition)options.afterTransition(transition);
      if(!current())return view;
      var loader=loaders[view]||loaders.home;
      if(options.runLoader)options.runLoader(loader,routeTicket);
      else if(loader)loader();
      return view;
    }

    function replaceCurrent(view){
      view=resolve(view);
      try{history.replaceState({view:view},'','/dashboard/'+view);}catch(e){}
      return view;
    }

    function handlePopState(event){
      return switchView(event&&event.state&&event.state.view?event.state.view:fromLocation(),true);
    }

    return {
      resolve:resolve,
      fromLocation:fromLocation,
      switchView:switchView,
      replaceCurrent:replaceCurrent,
      handlePopState:handlePopState
    };
  }

  global.FreqViewRouter={create:create};
})(window);
